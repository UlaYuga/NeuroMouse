"""Adversarial probe suite — the escape→harden gate.

Every probe is a *method module* that tries to break out of the sandbox:
network egress, filesystem escape, process spawning, native code via ctypes,
CPU/wall-clock exhaustion, OOM, fork bombs, and secret/env harvesting. Each test
asserts the attempt is *contained* (a ``SandboxError``) and, for side-effecting
probes, that the real-world side effect never happened.

Containment is proven two ways: an exception surfaces, AND — for probes that
swallow our :class:`SandboxPolicyViolation` and return normally — the evidence
of success (a written file, fetched bytes, a leaked secret) is absent.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from neuromouse_sandbox import MethodRef, SandboxLimits, run_in_sandbox
from neuromouse_sandbox.runner import (
    SandboxError,
    SandboxPolicyViolation,
    SandboxResourceLimit,
    SandboxTimeout,
)

ProbeRef = Callable[[str], MethodRef]


def _assert_not_kernel_fail_closed(exc: SandboxError) -> None:
    """A fail-closed missing kernel layer is not proof the hostile probe ran."""

    if isinstance(exc, SandboxPolicyViolation) and (
        exc.blocked_event or ""
    ).startswith("kernel.isolation."):
        raise AssertionError(
            "kernel isolation failed before the hostile probe executed"
        ) from exc
    if "kernel isolation unavailable" in str(exc).lower():
        raise AssertionError(
            "kernel isolation was unavailable before the hostile probe executed"
        ) from exc


# --------------------------------------------------------------------------- #
# Network egress
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("probe", ["net_connect", "net_dns"])
def test_network_egress_is_blocked(
    probe: str, probe_ref: ProbeRef, fast_limits: SandboxLimits
) -> None:
    with pytest.raises(SandboxPolicyViolation) as excinfo:
        run_in_sandbox(probe_ref(probe), dataset=None, params={}, limits=fast_limits)
    assert (excinfo.value.blocked_event or "").startswith("socket.")


def test_network_egress_blocked_even_when_method_swallows(
    probe_ref: ProbeRef, fast_limits: SandboxLimits
) -> None:
    # net_urllib catches our exception and returns normally; the proof of
    # containment is that no bytes were ever fetched from the network.
    try:
        result = run_in_sandbox(
            probe_ref("net_urllib"), dataset=None, params={}, limits=fast_limits
        )
    except SandboxError as exc:
        _assert_not_kernel_fail_closed(exc)
        return
    assert result["fetched"] is None


# --------------------------------------------------------------------------- #
# Filesystem escape
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("probe", ["fs_read_ssh", "fs_read_etc"])
def test_filesystem_reads_outside_allowlist_blocked(
    probe: str, probe_ref: ProbeRef, fast_limits: SandboxLimits
) -> None:
    with pytest.raises(SandboxPolicyViolation) as excinfo:
        run_in_sandbox(probe_ref(probe), dataset=None, params={}, limits=fast_limits)
    _assert_not_kernel_fail_closed(excinfo.value)


def test_filesystem_write_into_home_blocked(
    probe_ref: ProbeRef, fast_limits: SandboxLimits
) -> None:
    sentinel = Path.home() / ".nm_sandbox_pwned"
    sentinel.unlink(missing_ok=True)
    try:
        # HOME is scrubbed to the sandbox workdir, so a write to "~" lands inside
        # the sandbox (harmless), not the real home. An outright block OR the
        # scrub-redirect is acceptable — what matters is the real home is untouched
        # (this differs cross-platform: macOS /var symlink made it raise, Linux
        # redirects the write into the workdir).
        try:
            run_in_sandbox(probe_ref("fs_write_home"), dataset=None, params={}, limits=fast_limits)
        except SandboxPolicyViolation as exc:
            _assert_not_kernel_fail_closed(exc)
        assert not sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)


def test_filesystem_write_to_abs_path_blocked_even_when_swallowed(
    probe_ref: ProbeRef, fast_limits: SandboxLimits
) -> None:
    sentinel = Path("/tmp/nm_sandbox_pwned_abs")
    sentinel.unlink(missing_ok=True)
    try:
        try:
            result = run_in_sandbox(
                probe_ref("fs_write_abs"), dataset=None, params={}, limits=fast_limits
            )
            assert result["wrote"] is False
        except SandboxError as exc:
            _assert_not_kernel_fail_closed(exc)
            pass
        assert not sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Process spawning / native code
# --------------------------------------------------------------------------- #
def test_subprocess_spawn_blocked(probe_ref: ProbeRef, fast_limits: SandboxLimits) -> None:
    with pytest.raises(SandboxPolicyViolation) as excinfo:
        run_in_sandbox(probe_ref("subprocess_spawn"), dataset=None, params={}, limits=fast_limits)
    _assert_not_kernel_fail_closed(excinfo.value)


def test_shell_command_blocked_even_when_swallowed(
    probe_ref: ProbeRef, fast_limits: SandboxLimits
) -> None:
    sentinel = Path("/tmp/nm_sandbox_ossystem")
    sentinel.unlink(missing_ok=True)
    try:
        try:
            result = run_in_sandbox(
                probe_ref("os_system_spawn"), dataset=None, params={}, limits=fast_limits
            )
            # A blocked shell call returns non-zero/None: the command never ran.
            assert not result["rc"]
        except SandboxError as exc:
            _assert_not_kernel_fail_closed(exc)
            pass
        assert not sentinel.exists()
    finally:
        sentinel.unlink(missing_ok=True)


def test_ctypes_native_escape_blocked(probe_ref: ProbeRef, fast_limits: SandboxLimits) -> None:
    with pytest.raises(SandboxPolicyViolation) as excinfo:
        run_in_sandbox(probe_ref("ctypes_dlopen"), dataset=None, params={}, limits=fast_limits)
    blocked = excinfo.value.blocked_event or ""
    assert blocked.startswith("ctypes.") or blocked == "open"


# --------------------------------------------------------------------------- #
# Resource exhaustion
# --------------------------------------------------------------------------- #
def test_cpu_bomb_contained(probe_ref: ProbeRef) -> None:
    limits = SandboxLimits(wall_clock_sec=8.0, cpu_sec=2, memory_bytes=512 * 1024 * 1024)
    with pytest.raises((SandboxResourceLimit, SandboxTimeout)):
        run_in_sandbox(probe_ref("infinite_loop_cpu"), dataset=None, params={}, limits=limits)


def test_sleep_hang_contained_by_wall_clock(probe_ref: ProbeRef) -> None:
    limits = SandboxLimits(wall_clock_sec=2.0, cpu_sec=4)
    with pytest.raises(SandboxTimeout):
        run_in_sandbox(probe_ref("infinite_loop_sleep"), dataset=None, params={}, limits=limits)


def test_oom_contained(probe_ref: ProbeRef) -> None:
    limits = SandboxLimits(
        wall_clock_sec=15.0, cpu_sec=12, memory_bytes=400 * 1024 * 1024, max_processes=64
    )
    with pytest.raises(SandboxError) as excinfo:
        run_in_sandbox(probe_ref("oom"), dataset=None, params={}, limits=limits)
    # Either the Linux RLIMIT_AS bit, or the cross-platform RSS watchdog killed it.
    assert isinstance(excinfo.value, (SandboxResourceLimit, SandboxTimeout)) or "memory" in str(
        excinfo.value
    ).lower()


def test_fork_bomb_contained(probe_ref: ProbeRef, fast_limits: SandboxLimits) -> None:
    # Children stay alive; concurrent count is capped by RLIMIT_NPROC so the
    # number of successful forks can never reach the probe's attempt ceiling,
    # and the parent reaps the whole group afterwards.
    try:
        result = run_in_sandbox(
            probe_ref("fork_bomb"), dataset=None, params={}, limits=fast_limits
        )
    except SandboxError as exc:
        _assert_not_kernel_fail_closed(exc)
        return
    assert result["forks_succeeded"] <= fast_limits.max_processes


# --------------------------------------------------------------------------- #
# Secret / environment harvesting
# --------------------------------------------------------------------------- #
def test_environment_is_scrubbed_of_inherited_secrets(
    probe_ref: ProbeRef, fast_limits: SandboxLimits, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "DO-NOT-LEAK-7f3a9c"
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret)
    monkeypatch.setenv("NEUROMOUSE_API_TOKEN", secret)

    result = run_in_sandbox(probe_ref("read_env"), dataset=None, params={}, limits=fast_limits)
    env = result["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "NEUROMOUSE_API_TOKEN" not in env
    assert secret not in env.values()
    # Sanity: the parent really does hold the secret we expect to be filtered.
    assert os.environ["AWS_SECRET_ACCESS_KEY"] == secret
