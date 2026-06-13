"""Linux kernel isolation helpers for the sandbox worker.

The Python audit hook is the portable policy layer. This module adds a hosted
Linux defense-in-depth layer with seccomp-bpf through libseccomp. It intentionally
uses a deny-list profile rather than a syscall allow-list because the worker is a
Python interpreter running legitimate scientific code; the goal is to close the
known kernel escape primitives without making normal pure-Python methods brittle.
"""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

KERNEL_ENV = "NEUROMOUSE_SANDBOX_KERNEL"

KernelMode = Literal["off", "auto", "required"]
KernelPhase = Literal["loader", "compute", "filesystem"]

_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO_BASE = 0x00050000

_PR_SET_DUMPABLE = 4
_PR_SET_NO_NEW_PRIVS = 38
_SECCOMP_MISSING = "libseccomp.so.2 is not available"
_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1

_LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
_LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
_LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
_LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
_LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
_LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
_LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
_LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
_LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
_LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
_LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
_LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
_LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
_LANDLOCK_ACCESS_FS_REFER = 1 << 13
_LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

_LANDLOCK_READ_ACCESS = (
    _LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR
)
_LANDLOCK_WRITE_ACCESS_V1 = (
    _LANDLOCK_ACCESS_FS_WRITE_FILE
    | _LANDLOCK_ACCESS_FS_REMOVE_DIR
    | _LANDLOCK_ACCESS_FS_REMOVE_FILE
    | _LANDLOCK_ACCESS_FS_MAKE_CHAR
    | _LANDLOCK_ACCESS_FS_MAKE_DIR
    | _LANDLOCK_ACCESS_FS_MAKE_REG
    | _LANDLOCK_ACCESS_FS_MAKE_SOCK
    | _LANDLOCK_ACCESS_FS_MAKE_FIFO
    | _LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | _LANDLOCK_ACCESS_FS_MAKE_SYM
)

_MODE_ALIASES: dict[str, KernelMode] = {
    "0": "off",
    "false": "off",
    "no": "off",
    "off": "off",
    "disable": "off",
    "disabled": "off",
    "auto": "auto",
    "1": "required",
    "true": "required",
    "yes": "required",
    "on": "required",
    "require": "required",
    "required": "required",
    "seccomp": "required",
}

_LOADER_DENY_SYSCALLS = (
    # Network egress and listeners, including raw socket syscalls that bypass
    # Python's socket audit events.
    "socket",
    "socketpair",
    "connect",
    "accept",
    "accept4",
    "bind",
    "listen",
    "getsockname",
    "getpeername",
    "sendto",
    "sendmsg",
    "sendmmsg",
    "recvfrom",
    "recvmsg",
    "recvmmsg",
    "shutdown",
    "setsockopt",
    "getsockopt",
    # Process creation, exec, and namespace entry/creation.
    "fork",
    "vfork",
    "clone",
    "clone3",
    "execve",
    "execveat",
    "unshare",
    "setns",
    # Debugging/introspection and cross-process memory.
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "pidfd_getfd",
    # Mount/chroot/kernel mutation and other host-control surfaces.
    "mount",
    "umount",
    "umount2",
    "pivot_root",
    "chroot",
    "open_tree",
    "move_mount",
    "fsopen",
    "fsconfig",
    "fsmount",
    "fspick",
    "mount_setattr",
    "swapon",
    "swapoff",
    "reboot",
    "kexec_load",
    "kexec_file_load",
    "init_module",
    "finit_module",
    "delete_module",
    "bpf",
    "perf_event_open",
    "userfaultfd",
    "keyctl",
    "add_key",
    "request_key",
    "iopl",
    "ioperm",
    "acct",
    "sethostname",
    "setdomainname",
    # io_uring can be a broad async syscall surface; methods do not need it.
    "io_uring_setup",
    "io_uring_enter",
    "io_uring_register",
)

_COMPUTE_DENY_SYSCALLS = (
    # After the untrusted module is loaded, pure compute should not open more
    # host files. This closes raw openat('/proc/...') bypasses of the audit hook.
    "open",
    "openat",
    "openat2",
    "creat",
    "open_by_handle_at",
    "name_to_handle_at",
    "readlink",
    "readlinkat",
)


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _LandlockPathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


class KernelIsolationError(RuntimeError):
    """Raised when required kernel isolation cannot be installed."""


@dataclass(frozen=True)
class KernelIsolationResult:
    enabled: bool
    phase: KernelPhase
    mode: KernelMode
    rules_loaded: int = 0
    reason: str | None = None


def kernel_mode_from_env(env: Mapping[str, str] | None = None) -> KernelMode:
    """Return the configured kernel mode.

    Defaults to ``auto`` so Linux environments with libseccomp get the kernel
    layer automatically, while macOS and other dev platforms keep the Python
    policy fallback. The backend container sets ``required`` to fail closed.
    """

    source = os.environ if env is None else env
    raw = source.get(KERNEL_ENV, "auto").strip().lower()
    try:
        return _MODE_ALIASES[raw]
    except KeyError as exc:
        allowed = ", ".join(sorted(set(_MODE_ALIASES)))
        raise KernelIsolationError(
            f"invalid {KERNEL_ENV}={raw!r}; expected one of: {allowed}"
        ) from exc


def kernel_env_for_child(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Whitelisted kernel-mode environment to pass into the scrubbed child."""

    source = os.environ if env is None else env
    if KERNEL_ENV not in source:
        return {}
    # Validate before forwarding so a typo fails in the parent test surface.
    mode = kernel_mode_from_env(source)
    return {KERNEL_ENV: mode}


def apply_kernel_isolation(
    *,
    mode: KernelMode | str | None = None,
    phase: KernelPhase = "loader",
) -> KernelIsolationResult:
    """Install the Linux seccomp-bpf profile for the current process.

    ``phase="loader"`` blocks network/process/namespace/host-control syscalls
    before untrusted import. ``phase="compute"`` stacks an additional no-new-file
    profile immediately before ``compute`` runs.
    """

    selected = _normalize_mode(mode)
    if selected == "off":
        return KernelIsolationResult(enabled=False, phase=phase, mode=selected, reason="disabled")
    if sys.platform != "linux":
        return _unavailable(selected, phase, "seccomp-bpf is only available on Linux")
    if phase not in ("loader", "compute"):
        raise KernelIsolationError(f"unknown kernel isolation phase: {phase!r}")

    try:
        libseccomp = _load_libseccomp()
    except KernelIsolationError as exc:
        return _unavailable(selected, phase, str(exc))

    _set_no_new_privs(selected)
    if phase == "loader":
        _set_not_dumpable(selected)
        syscalls = _LOADER_DENY_SYSCALLS
    else:
        syscalls = _COMPUTE_DENY_SYSCALLS
    rules_loaded = _load_seccomp_rules(libseccomp, syscalls, selected)
    return KernelIsolationResult(
        enabled=True,
        phase=phase,
        mode=selected,
        rules_loaded=rules_loaded,
    )


def apply_kernel_filesystem_policy(
    *,
    mode: KernelMode | str | None = None,
    read_allow_prefixes: tuple[str, ...],
    write_allow_prefixes: tuple[str, ...],
) -> KernelIsolationResult:
    """Apply Linux Landlock path confinement for raw filesystem syscalls.

    This closes raw ``openat('/proc/...')`` style bypasses that seccomp-bpf
    cannot path-filter. It is installed before untrusted import so imports can
    still read package/method files under the explicit allow-list.
    """

    selected = _normalize_mode(mode)
    phase: KernelPhase = "filesystem"
    if selected == "off":
        return KernelIsolationResult(enabled=False, phase=phase, mode=selected, reason="disabled")
    if sys.platform != "linux":
        return _unavailable(selected, phase, "Landlock is only available on Linux")

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = _landlock_abi(libc)
    if abi <= 0:
        return _unavailable(selected, phase, "Landlock is not supported by this kernel")

    handled_access = _landlock_handled_access(abi)
    ruleset_attr = _LandlockRulesetAttr(handled_access)
    ruleset_fd = _syscall(
        libc,
        _LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(ctypes.addressof(ruleset_attr)),
        ctypes.c_size_t(ctypes.sizeof(ruleset_attr)),
        ctypes.c_uint(0),
    )
    if ruleset_fd < 0:
        return _landlock_unavailable(selected, phase, "landlock_create_ruleset")

    opened_fds: list[int] = []
    rules_loaded = 0
    try:
        read_access = _LANDLOCK_READ_ACCESS & handled_access
        write_access = (read_access | _landlock_write_access(abi)) & handled_access
        traversal_access = (
            _LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_READ_DIR
        ) & handled_access
        for path in _ancestor_dirs((*read_allow_prefixes, *write_allow_prefixes)):
            rules_loaded += _add_landlock_path_rule(
                libc,
                ruleset_fd,
                path,
                traversal_access,
                opened_fds,
                selected,
            )
        for path in _unique_existing_dirs(read_allow_prefixes):
            rules_loaded += _add_landlock_path_rule(
                libc,
                ruleset_fd,
                path,
                read_access,
                opened_fds,
                selected,
            )
        for path in _unique_existing_dirs(write_allow_prefixes):
            rules_loaded += _add_landlock_path_rule(
                libc,
                ruleset_fd,
                path,
                write_access,
                opened_fds,
                selected,
            )
        if rules_loaded == 0 and selected == "required":
            raise KernelIsolationError("Landlock loaded zero filesystem rules")
        _set_no_new_privs(selected)
        rc = _syscall(libc, _LANDLOCK_RESTRICT_SELF, ctypes.c_int(ruleset_fd), ctypes.c_uint(0))
        if rc < 0:
            return _landlock_unavailable(selected, phase, "landlock_restrict_self")
    finally:
        for fd in opened_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.close(ruleset_fd)
        except OSError:
            pass

    return KernelIsolationResult(
        enabled=True,
        phase=phase,
        mode=selected,
        rules_loaded=rules_loaded,
    )


def _normalize_mode(mode: KernelMode | str | None) -> KernelMode:
    if mode is None:
        return kernel_mode_from_env()
    try:
        return _MODE_ALIASES[str(mode).strip().lower()]
    except KeyError as exc:
        raise KernelIsolationError(f"invalid kernel isolation mode: {mode!r}") from exc


def _unavailable(
    mode: KernelMode,
    phase: KernelPhase,
    reason: str,
) -> KernelIsolationResult:
    if mode == "required":
        raise KernelIsolationError(reason)
    return KernelIsolationResult(enabled=False, phase=phase, mode=mode, reason=reason)


def _load_libseccomp() -> ctypes.CDLL:
    try:
        lib = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    except OSError as exc:
        raise KernelIsolationError(_SECCOMP_MISSING) from exc

    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    return lib


def _set_no_new_privs(mode: KernelMode) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rc = libc.prctl(
        ctypes.c_int(_PR_SET_NO_NEW_PRIVS),
        ctypes.c_ulong(1),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
    )
    if rc != 0 and mode == "required":
        err = ctypes.get_errno()
        raise KernelIsolationError(f"prctl(PR_SET_NO_NEW_PRIVS) failed: {os.strerror(err)}")


def _set_not_dumpable(mode: KernelMode) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rc = libc.prctl(
        ctypes.c_int(_PR_SET_DUMPABLE),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
        ctypes.c_ulong(0),
    )
    if rc != 0 and mode == "required":
        err = ctypes.get_errno()
        raise KernelIsolationError(f"prctl(PR_SET_DUMPABLE) failed: {os.strerror(err)}")


def _load_seccomp_rules(
    lib: ctypes.CDLL,
    syscall_names: tuple[str, ...],
    mode: KernelMode,
) -> int:
    ctx = lib.seccomp_init(ctypes.c_uint32(_SCMP_ACT_ALLOW))
    if not ctx:
        raise KernelIsolationError("seccomp_init failed")
    rules_loaded = 0
    try:
        action = _SCMP_ACT_ERRNO_BASE | errno.EPERM
        for name in syscall_names:
            number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0:
                continue
            rc = lib.seccomp_rule_add(
                ctypes.c_void_p(ctx),
                ctypes.c_uint32(action),
                ctypes.c_int(number),
                ctypes.c_uint(0),
            )
            if rc < 0:
                raise KernelIsolationError(
                    f"seccomp_rule_add({name}) failed: {os.strerror(-rc)}"
                )
            rules_loaded += 1
        if rules_loaded == 0 and mode == "required":
            raise KernelIsolationError("seccomp loaded zero syscall rules")
        rc = lib.seccomp_load(ctypes.c_void_p(ctx))
        if rc < 0:
            raise KernelIsolationError(f"seccomp_load failed: {os.strerror(-rc)}")
    finally:
        lib.seccomp_release(ctypes.c_void_p(ctx))
    return rules_loaded


def _landlock_abi(libc: ctypes.CDLL) -> int:
    ctypes.set_errno(0)
    rc = _syscall(
        libc,
        _LANDLOCK_CREATE_RULESET,
        ctypes.c_void_p(0),
        ctypes.c_size_t(0),
        ctypes.c_uint(_LANDLOCK_CREATE_RULESET_VERSION),
    )
    return int(rc)


def _landlock_handled_access(abi: int) -> int:
    access = _LANDLOCK_READ_ACCESS | _LANDLOCK_WRITE_ACCESS_V1
    if abi >= 2:
        access |= _LANDLOCK_ACCESS_FS_REFER
    if abi >= 3:
        access |= _LANDLOCK_ACCESS_FS_TRUNCATE
    return access


def _landlock_write_access(abi: int) -> int:
    access = _LANDLOCK_WRITE_ACCESS_V1
    if abi >= 2:
        access |= _LANDLOCK_ACCESS_FS_REFER
    if abi >= 3:
        access |= _LANDLOCK_ACCESS_FS_TRUNCATE
    return access


def _add_landlock_path_rule(
    libc: ctypes.CDLL,
    ruleset_fd: int,
    path: str,
    allowed_access: int,
    opened_fds: list[int],
    mode: KernelMode,
) -> int:
    if allowed_access == 0:
        return 0
    flags = getattr(os, "O_PATH", os.O_RDONLY) | getattr(os, "O_DIRECTORY", 0) | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if mode == "required":
            raise KernelIsolationError(f"cannot open Landlock path {path}: {exc}") from exc
        return 0
    opened_fds.append(fd)
    attr = _LandlockPathBeneathAttr(allowed_access, fd)
    rc = _syscall(
        libc,
        _LANDLOCK_ADD_RULE,
        ctypes.c_int(ruleset_fd),
        ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH),
        ctypes.c_void_p(ctypes.addressof(attr)),
        ctypes.c_uint(0),
    )
    if rc < 0:
        if mode == "required":
            err = ctypes.get_errno()
            raise KernelIsolationError(f"landlock_add_rule({path}) failed: {os.strerror(err)}")
        return 0
    return 1


def _landlock_unavailable(
    mode: KernelMode,
    phase: KernelPhase,
    syscall_name: str,
) -> KernelIsolationResult:
    err = ctypes.get_errno()
    reason = f"{syscall_name} failed: {os.strerror(err)}"
    if mode == "required":
        raise KernelIsolationError(reason)
    return KernelIsolationResult(enabled=False, phase=phase, mode=mode, reason=reason)


def _unique_existing_dirs(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    dirs: list[str] = []
    for raw in prefixes:
        if not raw:
            continue
        path = os.path.abspath(raw)
        if not os.path.isdir(path) or path in seen:
            continue
        seen.add(path)
        dirs.append(path)
    return tuple(dirs)


def _ancestor_dirs(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    dirs: list[str] = []
    for path in _unique_existing_dirs(prefixes):
        cursor = os.path.abspath(path)
        chain: list[str] = []
        while True:
            parent = os.path.dirname(cursor)
            if parent == cursor:
                chain.append(cursor)
                break
            chain.append(parent)
            cursor = parent
        for ancestor in reversed(chain):
            if ancestor not in seen and os.path.isdir(ancestor):
                seen.add(ancestor)
                dirs.append(ancestor)
    return tuple(dirs)


def _syscall(libc: ctypes.CDLL, number: int, *args: object) -> int:
    ctypes.set_errno(0)
    return int(libc.syscall(ctypes.c_long(number), *args))
