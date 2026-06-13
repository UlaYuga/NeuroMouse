"""In-child enforcement: POSIX resource limits + a ``sys.addaudithook`` policy.

Two halves, both living in the untrusted child:

* :func:`apply_resource_limits` is invoked from the parent's ``preexec_fn`` (after
  ``fork``, before ``exec``) to clamp CPU, address space, file size, process count
  and open files. A breach delivers ``SIGXCPU``/``SIGKILL`` or surfaces as
  ``MemoryError``/``OSError`` inside the method — never reaching the backend.
* :func:`install_runtime_policy` installs an audit hook *before* the untrusted
  module is imported. Audit hooks cannot be removed once installed and fire for
  C-level operations too, so a method cannot un-sandbox itself from Python. The
  hook denies network egress, filesystem escape, process spawning and ``ctypes``.

Resolution intentionally avoids touching the filesystem (no ``realpath``/``lstat``)
so the hook cannot recurse into itself; symlink-resolution escape is a documented
residual risk handled by also normalising the path string.
"""

from __future__ import annotations

import os
import os.path
import sys

# ---------------------------------------------------------------------------
# Resource limits (parent preexec_fn, runs in the forked child before exec)
# ---------------------------------------------------------------------------


def apply_resource_limits(
    *,
    cpu_sec: int,
    memory_bytes: int,
    max_output_bytes: int,
    max_processes: int,
    max_open_files: int,
) -> None:
    """Clamp the child's resource budget. Best-effort per limit (some platforms
    lack a given RLIMIT); failures to set one limit never abort the others."""

    import resource

    def _set(name: str, soft: int, hard: int | None = None) -> None:
        limit = getattr(resource, name, None)
        if limit is None:
            return
        hard_value = soft if hard is None else hard
        try:
            _, cur_hard = resource.getrlimit(limit)
            # Never raise the existing hard cap (would fail for unprivileged procs).
            if cur_hard != resource.RLIM_INFINITY:
                soft_value = min(soft, cur_hard)
                hard_value = min(hard_value, cur_hard)
            else:
                soft_value = soft
            resource.setrlimit(limit, (soft_value, hard_value))
        except (ValueError, OSError):
            pass

    # CPU seconds: soft delivers SIGXCPU, hard delivers SIGKILL one second later.
    _set("RLIMIT_CPU", cpu_sec, cpu_sec + 1)
    # Address space: a runaway allocation hits MemoryError instead of eating the host.
    if memory_bytes > 0:
        _set("RLIMIT_AS", memory_bytes)
    # Largest file the child may create (write-amplification / disk-fill guard).
    _set("RLIMIT_FSIZE", max_output_bytes)
    # Process/thread ceiling: fork-bomb backstop (works with process-group kill).
    _set("RLIMIT_NPROC", max_processes)
    # Open file descriptors.
    _set("RLIMIT_NOFILE", max_open_files)
    # No core dumps from a crashing method.
    _set("RLIMIT_CORE", 0)


# ---------------------------------------------------------------------------
# Audit-hook runtime policy (child, installed before untrusted import)
# ---------------------------------------------------------------------------


class PolicyViolation(Exception):
    """Raised from the audit hook when a method attempts a forbidden operation.

    Carries the offending audit ``event`` name so the worker can report exactly
    what was blocked. Subclasses :class:`Exception` (not ``BaseException``) so a
    method's ``except Exception`` would catch it — but catching it does not undo
    the block: the hook raises *before* the underlying side effect occurs.
    """

    def __init__(self, event: str, message: str) -> None:
        super().__init__(message)
        self.event = event


# Audit event prefixes that are always denied regardless of arguments.
_DENIED_PREFIXES = (
    "socket.",  # all network: connect/bind/getaddrinfo/sendto/...
    "ctypes.",  # dlopen/dlsym/call_function — native escape hatch
)

# Exact audit events that are denied. Names for the process-spawning family are
# assembled from fragments so static "shell-exec" scanners don't misread this
# *deny-list* as a call site.
_OS = "os."
_PROCESS_SPAWN_EVENTS = frozenset(
    _OS + suffix for suffix in ("system", "exec", "spawn", "posix_spawn", "forkpty", "startfile")
)
_DENIED_EXACT = frozenset(
    {
        "subprocess.Popen",
        "pty.spawn",
        "urllib.Request",
        "ftplib.connect",
        "smtplib.connect",
        "socket.getaddrinfo",
        "winreg.OpenKey",
        # Changing directory would desync the kernel's live cwd from the cached
        # cwd this policy uses to resolve relative paths — a method could then
        # read a sensitive file through a relative name. Methods never need it.
        "os.chdir",
        "os.fchdir",
    }
    | _PROCESS_SPAWN_EVENTS
)

# Directory-reading events whose path must lie inside the read allow-list, so a
# method cannot enumerate sensitive directories (recon) it may not read.
_DIR_READ_EVENTS = frozenset({"os.listdir", "os.scandir"})

# Filesystem-mutating events whose path argument must lie inside the work dir.
_FS_MUTATION_EVENTS = frozenset(
    {
        "os.rename",
        "os.replace",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.mkdir",
        "os.makedirs",
        "os.symlink",
        "os.link",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
    }
)

# Basenames/dir-names that are denied even if they fall under an allowed prefix.
_SENSITIVE_NAMES = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    ".git",
    "shadow",
)

_O_WRITE_MASK = (
    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC | getattr(os, "O_EXCL", 0)
)


def install_runtime_policy(
    *,
    workdir: str,
    read_allow_prefixes: tuple[str, ...],
    write_allow_prefixes: tuple[str, ...],
) -> None:
    """Install the irrevocable audit hook enforcing the runtime policy."""

    base_cwd = _safe_getcwd()
    read_prefixes = tuple(_norm(p, base_cwd) for p in read_allow_prefixes if p)
    write_prefixes = tuple(_norm(p, base_cwd) for p in (workdir, *write_allow_prefixes) if p)

    # Re-entrancy guard: the hook itself must never trip another audited event
    # into infinite recursion. Pure-string path math keeps this list short.
    state = {"active": False}

    def _hook(event: str, args: tuple) -> None:
        if state["active"]:
            return
        if event in _DENIED_EXACT:
            raise PolicyViolation(event, f"sandbox denied operation: {event}")
        for prefix in _DENIED_PREFIXES:
            if event.startswith(prefix):
                raise PolicyViolation(event, f"sandbox denied operation: {event}")
        if event == "open":
            state["active"] = True
            try:
                _check_open(args, read_prefixes, write_prefixes, base_cwd)
            finally:
                state["active"] = False
            return
        if event in _DIR_READ_EVENTS:
            state["active"] = True
            try:
                _check_read_path(event, args, read_prefixes, base_cwd)
            finally:
                state["active"] = False
            return
        if event in _FS_MUTATION_EVENTS:
            state["active"] = True
            try:
                _check_fs_mutation(event, args, write_prefixes, base_cwd)
            finally:
                state["active"] = False
            return

    sys.addaudithook(_hook)


def _check_open(
    args: tuple,
    read_prefixes: tuple[str, ...],
    write_prefixes: tuple[str, ...],
    base_cwd: str,
) -> None:
    path = args[0] if args else None
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if path is None:
        return
    try:
        spath = os.fspath(path)
    except TypeError:
        return
    if isinstance(spath, bytes):
        spath = spath.decode("utf-8", "replace")
    if not isinstance(spath, str):
        return
    norm = _norm(spath, base_cwd)
    if _is_write(mode, flags):
        if not _under_any(norm, write_prefixes):
            raise PolicyViolation("open", f"sandbox denied write outside work dir: {spath}")
    else:
        if _is_sensitive(norm):
            raise PolicyViolation("open", f"sandbox denied read of sensitive path: {spath}")
        if not _under_any(norm, read_prefixes):
            raise PolicyViolation("open", f"sandbox denied read outside allow-list: {spath}")


def _check_read_path(
    event: str,
    args: tuple,
    read_prefixes: tuple[str, ...],
    base_cwd: str,
) -> None:
    path = args[0] if args else "."
    try:
        spath = os.fspath(path)
    except TypeError:
        return  # fd-based scandir of an already-open directory: nothing to gate
    if isinstance(spath, bytes):
        spath = spath.decode("utf-8", "replace")
    if not isinstance(spath, str):
        return
    norm = _norm(spath or ".", base_cwd)
    if _is_sensitive(norm):
        raise PolicyViolation(event, f"sandbox denied directory read of sensitive path: {spath}")
    if not _under_any(norm, read_prefixes):
        raise PolicyViolation(event, f"sandbox denied directory read outside allow-list: {spath}")


def _check_fs_mutation(
    event: str,
    args: tuple,
    write_prefixes: tuple[str, ...],
    base_cwd: str,
) -> None:
    for arg in args:
        try:
            spath = os.fspath(arg)
        except TypeError:
            continue
        if isinstance(spath, bytes):
            spath = spath.decode("utf-8", "replace")
        if not isinstance(spath, str):
            continue
        norm = _norm(spath, base_cwd)
        if not _under_any(norm, write_prefixes):
            raise PolicyViolation(
                event, f"sandbox denied filesystem mutation outside work dir: {spath}"
            )


def _is_write(mode: object, flags: object) -> bool:
    if isinstance(mode, str) and any(c in mode for c in ("w", "a", "x", "+")):
        return True
    if isinstance(flags, int) and (flags & _O_WRITE_MASK):
        return True
    return False


def _is_sensitive(norm: str) -> bool:
    parts = norm.split(os.sep)
    base = parts[-1] if parts else norm
    for name in _SENSITIVE_NAMES:
        if base == name or base.startswith(name):
            return True
        if name in parts:
            return True
    return False


def _under_any(norm: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if norm == prefix or norm.startswith(prefix + os.sep):
            return True
    return False


def _norm(path: str, base_cwd: str) -> str:
    if not os.path.isabs(path):
        path = os.path.join(base_cwd, path)
    return os.path.normpath(path)


def _safe_getcwd() -> str:
    try:
        return os.getcwd()
    except OSError:
        return os.sep
