"""Extended adversarial probes — the vectors surfaced by escape→harden rounds 2-5.

Each round added new break-out attempts; the two that initially *escaped* drove a
hardening change, after which they are contained here:

* Round 2 — directory enumeration (``os.listdir``/``os.scandir`` of ``/etc``)
  escaped; hardened by gating directory reads through the read allow-list.
* Round 4 — ``os.chdir`` into a sensitive dir + a relative ``open`` escaped;
  hardened by denying ``os.chdir``/``os.fchdir`` so the cached-cwd path check
  cannot be desynced from the kernel's live cwd.

All other vectors (symlink plant, path traversal, low-level ``os.open``,
``multiprocessing``, result-envelope forgery, recursion/stack crash, dynamically
``exec``-ed network calls, ``/proc/self/environ``, SIGXCPU trapping, thread
bombs, self-rlimit-raising before OOM, local socketpairs) were contained on
first contact.

A probe is *contained* iff it either raises a ``SandboxError`` or returns with no
evidence of its side effect — proving that even a method which swallows our
:class:`SandboxPolicyViolation` cannot actually break out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from neuromouse_sandbox import MethodRef, SandboxLimits, run_in_sandbox
from neuromouse_sandbox.runner import SandboxError, SandboxMethodError

ProbeRef = Callable[[str], MethodRef]

_BASE = SandboxLimits(
    wall_clock_sec=8.0, cpu_sec=4, memory_bytes=512 * 1024 * 1024, max_processes=64
)

# (probe, limit-overrides, evidence-keys). Empty evidence-keys ⇒ the probe must
# raise (it cannot return normally). Non-empty ⇒ it may return, but every listed
# result key must be falsy (no successful side effect).
_PROBES: list[tuple[str, dict, tuple[str, ...]]] = [
    ("symlink_escape", {}, ("leaked",)),
    ("dir_enumerate", {}, ("listdir_etc", "scandir_home")),
    ("path_traversal", {}, ("leaked",)),
    ("os_open_read", {}, ("leaked",)),
    ("multiprocessing_spawn", {}, ("spawned",)),
    ("exec_dynamic", {}, ("leaked",)),
    ("proc_environ", {}, ("leaked",)),
    ("chdir_escape", {}, ("leaked",)),
    ("socketpair_local", {}, ("recv",)),
    # Must-raise vectors (no benign return path):
    ("output_tamper", {}, ()),
    ("recursion_bomb", {}, ()),
    ("sigxcpu_trap", {"wall_clock_sec": 10.0, "cpu_sec": 2}, ()),
    ("thread_bomb", {"wall_clock_sec": 3.0, "cpu_sec": 2}, ()),
    (
        "rlimit_raise_oom",
        {"wall_clock_sec": 15.0, "cpu_sec": 12, "memory_bytes": 400 * 1024 * 1024},
        (),
    ),
]


@pytest.mark.parametrize("name,overrides,evidence", _PROBES, ids=[p[0] for p in _PROBES])
def test_probe_is_contained(
    probe_ref: ProbeRef, name: str, overrides: dict, evidence: tuple[str, ...]
) -> None:
    limits = replace(_BASE, **overrides)
    try:
        result = run_in_sandbox(probe_ref(name), dataset=None, params={}, limits=limits)
    except SandboxError:
        return  # contained by exception
    assert evidence, f"{name} returned normally but was expected to be killed/blocked"
    for key in evidence:
        assert not result.get(key), f"{name} escaped: {key}={result.get(key)!r}"


def test_result_envelope_cannot_be_forged(probe_ref: ProbeRef) -> None:
    # output_tamper writes a fake "ok/forged" envelope to its guessed response
    # path. The real response lives outside the child's writable work dir, so the
    # parent must surface the method's genuine failure, never the forgery.
    with pytest.raises(SandboxMethodError) as excinfo:
        run_in_sandbox(probe_ref("output_tamper"), dataset=None, params={}, limits=_BASE)
    # The parent received the method's genuine RuntimeError, not the forged
    # ``status: ok`` envelope the probe tried to plant.
    assert "RuntimeError" in str(excinfo.value)
