"""Parent-side runner: spawn, constrain, and harvest the untrusted child.

:func:`run_in_sandbox` is the entire public surface the backend touches. It
serialises the request, launches ``python -m neuromouse_sandbox.worker`` in a
fresh process group with a scrubbed environment and POSIX resource limits, kills
the whole group if the wall-clock deadline passes, and maps the outcome onto a
small exception hierarchy. The backend translates any :class:`SandboxError` into
a graceful job failure — the untrusted code can never take the backend down.

The child is always launched as an argv list (never a shell string), so the
method reference and paths cannot be interpreted as shell syntax.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import resource  # noqa: F401 - imported in parent so preexec_fn never imports post-fork
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from neuromouse_sandbox.contract import (
    MODE_DESCRIBE,
    STATUS_METHOD_ERROR,
    STATUS_OK,
    STATUS_POLICY_VIOLATION,
    MethodRef,
    RequestEnvelope,
    ResponseEnvelope,
    SandboxLimits,
)
from neuromouse_sandbox.kernel import kernel_env_for_child
from neuromouse_sandbox.policy import apply_resource_limits


class SandboxError(Exception):
    """Base class for all sandbox-boundary failures."""


class SandboxTimeout(SandboxError):
    """The child exceeded its wall-clock deadline and was force-killed."""


class SandboxResourceLimit(SandboxError):
    """The child was killed by a resource limit (CPU/memory/etc.) or crashed
    without producing a structured response."""


class SandboxPolicyViolation(SandboxError):
    """The method attempted a forbidden operation (network/fs/proc/ctypes)."""

    def __init__(self, message: str, *, blocked_event: str | None = None) -> None:
        super().__init__(message)
        self.blocked_event = blocked_event


class SandboxMethodError(SandboxError):
    """The method ran inside the sandbox but failed gracefully (raised, bad
    inputs, non-conforming output, or an unloadable module)."""


_WORKER_MODULE = "neuromouse_sandbox.worker"

# How often the parent watchdog samples the child's wall-clock age and memory.
_POLL_INTERVAL_SEC = 0.03


def run_in_sandbox(
    method: MethodRef,
    dataset: dict[str, Any] | None,
    params: dict[str, Any] | None = None,
    *,
    limits: SandboxLimits | None = None,
    required_inputs: tuple[str, ...] = (),
    output_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run ``method.compute`` in an isolated subprocess and return its result.

    Raises a :class:`SandboxError` subclass on timeout, resource breach, policy
    violation, or method-level failure.
    """

    request = RequestEnvelope(
        method=method,
        dataset=dataset,
        params=dict(params or {}),
        required_inputs=tuple(required_inputs),
        output_fields=tuple(output_fields),
    )
    return _execute(request, limits or SandboxLimits())


def describe_in_sandbox(
    method: MethodRef,
    *,
    limits: SandboxLimits | None = None,
) -> dict[str, Any]:
    """Import an (untrusted) method in the sandbox and return its declared
    metadata (name, version, required inputs, params schema, output + panel).

    Importing a method module runs its top-level code, so registration must
    cross the same boundary as execution. ``compute`` is never called and no
    dataset is shipped. Raises a :class:`SandboxError` on any breach/failure.
    """

    request = RequestEnvelope(
        method=method,
        dataset=None,
        params={},
        required_inputs=(),
        output_fields=(),
        mode=MODE_DESCRIBE,
    )
    return _execute(request, limits or SandboxLimits())


def _execute(request: RequestEnvelope, budget: SandboxLimits) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="nm-sandbox-") as base:
        # The request/response/stderr files live in `base`; the child's cwd and
        # *only* writable area is the `work` subdir. Because the response file
        # sits outside `work`, an untrusted method cannot forge or truncate its
        # own result envelope (it can only write inside `work`).
        workdir = os.path.join(base, "work")
        os.mkdir(workdir)
        input_path = os.path.join(base, "request.json")
        output_path = os.path.join(base, "response.json")
        with open(input_path, "w", encoding="utf-8") as handle:
            handle.write(request.to_json())
        # Pre-create the result file so the child can open it for writing under
        # a filesystem policy that otherwise forbids creating new files.
        with open(output_path, "w", encoding="utf-8"):
            pass

        completed = _spawn(workdir, input_path, output_path, budget)
        return _harvest(completed, output_path, budget)


def _spawn(
    workdir: str,
    input_path: str,
    output_path: str,
    budget: SandboxLimits,
) -> subprocess.CompletedProcess[bytes]:
    def _preexec() -> None:  # runs in the forked child, before the image is replaced
        apply_resource_limits(
            cpu_sec=budget.cpu_sec,
            memory_bytes=budget.memory_bytes,
            max_output_bytes=budget.max_output_bytes,
            max_processes=budget.max_processes,
            max_open_files=budget.max_open_files,
        )

    # Child stderr goes to a file (not a PIPE) so the parent's watchdog loop can
    # never deadlock on a full pipe buffer if the method spams stderr. It lives
    # beside the response file, outside the child's writable work dir.
    stderr_path = os.path.join(os.path.dirname(workdir), "stderr.log")
    argv = [sys.executable, "-m", _WORKER_MODULE, input_path, output_path]
    with open(stderr_path, "wb") as errf:
        proc = subprocess.Popen(
            argv,
            cwd=workdir,
            env=_clean_env(workdir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errf,
            preexec_fn=_preexec,
            start_new_session=True,  # own process group → fork-bomb children die with it
            close_fds=True,
        )

    deadline = time.monotonic() + budget.wall_clock_sec
    # RLIMIT_AS is honoured on Linux (CI) but silently ignored on macOS, so the
    # parent independently polls resident memory and is the cross-platform OOM
    # backstop. Leave headroom for the interpreter + dataset baseline.
    mem_limit_kb = budget.memory_bytes // 1024 if budget.memory_bytes > 0 else 0
    breach: str | None = None
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        if time.monotonic() >= deadline:
            breach = "timeout"
            break
        if mem_limit_kb and _group_rss_kb(proc.pid) > mem_limit_kb:
            breach = "memory"
            break
        time.sleep(_POLL_INTERVAL_SEC)

    if breach is not None:
        _kill_group(proc)
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
        stderr_tail = _read_capped(stderr_path, 4096).decode("utf-8", "replace")[-1500:]
        if breach == "timeout":
            raise SandboxTimeout(
                f"method exceeded wall-clock limit of {budget.wall_clock_sec:g}s"
            )
        raise SandboxResourceLimit(
            f"method exceeded memory limit of {budget.memory_bytes} bytes; stderr: {stderr_tail}"
        )

    stderr = _read_capped(stderr_path, 1 << 20)
    # Reap any grandchildren the method spawned before exiting (e.g. a fork bomb
    # whose children outlive their parent): killing the session group leaves no
    # orphans lingering on the host.
    _kill_group(proc)
    return subprocess.CompletedProcess(proc.args, proc.returncode, b"", stderr)


def _harvest(
    completed: subprocess.CompletedProcess[bytes],
    output_path: str,
    budget: SandboxLimits,
) -> dict[str, Any]:
    raw = _read_capped(output_path, budget.max_output_bytes)
    stderr_tail = (completed.stderr or b"").decode("utf-8", "replace")[-1500:]

    if not raw:
        # No structured response: the child was killed by a limit or crashed.
        rc = completed.returncode
        if rc is not None and rc < 0:
            sig = -rc
            valid = {s.value for s in signal.Signals}
            name = signal.Signals(sig).name if sig in valid else str(sig)
            if sig in (signal.SIGXCPU, signal.SIGKILL):
                raise SandboxResourceLimit(
                    f"method killed by resource limit (signal {name}); stderr: {stderr_tail}"
                )
            raise SandboxResourceLimit(
                f"method process died (signal {name}); stderr: {stderr_tail}"
            )
        raise SandboxResourceLimit(
            f"method produced no response (exit {rc}); stderr: {stderr_tail}"
        )

    try:
        response = ResponseEnvelope.from_json(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - corrupt envelope ⇒ treat as crash
        raise SandboxResourceLimit(
            f"method response was unparseable: {exc}; stderr: {stderr_tail}"
        ) from exc

    if response.status == STATUS_OK:
        return response.result or {}
    if response.status == STATUS_POLICY_VIOLATION:
        raise SandboxPolicyViolation(
            response.error_message or "method attempted a forbidden operation",
            blocked_event=response.blocked_event,
        )
    if response.status == STATUS_METHOD_ERROR:
        raise SandboxMethodError(response.error_message or "method failed")
    # STATUS_BAD_REQUEST or anything unexpected.
    raise SandboxMethodError(response.error_message or f"sandbox error: {response.status}")


def _child_pythonpath() -> str:
    """``PYTHONPATH`` for the child: the parent's directory ``sys.path`` entries
    plus the explicit source roots of the NeuroMouse packages the worker needs.

    The explicit roots matter because editable installs expose packages through
    a meta-path finder rather than a raw ``src`` directory on ``sys.path``; a
    scrubbed-env child that only re-used ``sys.path`` would fail to import them.
    """

    roots = [p for p in sys.path if p and os.path.isdir(p)]
    for module_name in ("neuromouse_sandbox", "neuromouse_contract", "neuromouse_sdk"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        file = getattr(module, "__file__", None)
        if file:
            # .../<root>/<package>/__init__.py → <root>
            roots.append(os.path.dirname(os.path.dirname(os.path.abspath(file))))
    # Filesystem fallback: derive the workspace src roots from this file's known
    # location so the child resolves the packages even when the parent's
    # editable installs are unavailable (fresh checkout, broken .pth, etc.).
    # runner.py → <repo>/packages/sandbox/src/neuromouse_sandbox/runner.py
    here = os.path.abspath(__file__)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here)))))
    for rel in ("packages/sandbox/src", "contracts/src", "packages/sdk/src"):
        candidate = os.path.join(repo, *rel.split("/"))
        if os.path.isdir(candidate):
            roots.append(candidate)
    return os.pathsep.join(dict.fromkeys(roots))


def _clean_env(workdir: str) -> dict[str, str]:
    """A minimal environment: no inherited secrets, home/temp rooted in the work
    dir, single-threaded native libs, and just enough ``PYTHONPATH`` to import
    the worker and the NeuroMouse packages."""

    pythonpath = _child_pythonpath()
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": workdir,
        "TMPDIR": workdir,
        "TEMP": workdir,
        "TMP": workdir,
        "PYTHONPATH": pythonpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        # Keep native math libraries single-threaded: predictable CPU accounting
        # and one fewer fork-bomb vector.
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }
    env.update(kernel_env_for_child())
    return env


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _group_rss_kb(pid: int) -> int:
    """Resident memory (KiB) of the child's whole process group via ``ps``.

    Summing the group catches fork-and-allocate patterns, not just the lead
    process. Any failure (process already gone, ``ps`` unavailable) returns 0 so
    the watchdog never kills a healthy child on a transient read error.
    """

    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, OSError):
        return 0
    for selector in (["-g", str(pgid)], ["-p", str(pid)]):
        try:
            proc = subprocess.run(
                ["ps", "-o", "rss=", *selector],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        total = 0
        found = False
        for line in proc.stdout.decode("ascii", "replace").split():
            if line.isdigit():
                total += int(line)
                found = True
        if found:
            return total
    return 0


def _read_capped(path: str, cap: int) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(cap + 1)[:cap]
    except OSError:
        return b""
