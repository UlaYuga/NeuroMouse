"""Process-isolation boundary for untrusted NeuroMouse method/sorter code.

Third-party method code must never run in-process in the backend. This package
runs ``method.compute`` (and the untrusted module import + param construction it
implies) inside a short-lived subprocess that is wrapped in:

* POSIX resource limits (CPU seconds, address space, file size, process count);
* a hard wall-clock deadline enforced by killing the child's process group;
* a scrubbed environment (no inherited secrets) rooted in a throwaway work dir;
* a ``sys.addaudithook`` policy that denies network egress, filesystem escape,
  process spawning and ``ctypes``/dynamic-library access.

The public surface is the parent-side :func:`run_in_sandbox` runner, the
:class:`SandboxLimits` knob bag, the :class:`MethodRef` locator and the
:class:`SandboxError` exception hierarchy.
"""

from __future__ import annotations

from neuromouse_sandbox.contract import MethodRef, SandboxLimits
from neuromouse_sandbox.runner import (
    SandboxError,
    SandboxMethodError,
    SandboxPolicyViolation,
    SandboxResourceLimit,
    SandboxTimeout,
    run_in_sandbox,
)

__all__ = [
    "MethodRef",
    "SandboxLimits",
    "SandboxError",
    "SandboxMethodError",
    "SandboxPolicyViolation",
    "SandboxResourceLimit",
    "SandboxTimeout",
    "run_in_sandbox",
]
