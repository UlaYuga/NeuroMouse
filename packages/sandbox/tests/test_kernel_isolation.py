"""Linux kernel-enforcement probes for the sandbox worker.

These tests run the seccomp profile in a throwaway Python subprocess because a
loaded seccomp filter is intentionally irreversible for the current process.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from neuromouse_sandbox.runner import _clean_env

LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Linux-only kernel isolation probes require seccomp-bpf",
)


def test_clean_env_forwards_required_kernel_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEUROMOUSE_SANDBOX_KERNEL", "required")

    env = _clean_env("/tmp/nm-sandbox-work")

    assert env["NEUROMOUSE_SANDBOX_KERNEL"] == "required"


@LINUX_ONLY
@pytest.mark.parametrize("probe", ["socket", "ptrace", "unshare"])
def test_loader_seccomp_blocks_raw_syscalls(probe: str) -> None:
    result = _run_kernel_probe(probe)

    assert result["seccomp"] == "2"
    assert result["rc"] == -1
    assert result["errno"] == errno.EPERM


@LINUX_ONLY
def test_kernel_filesystem_policy_blocks_raw_proc_open() -> None:
    result = _run_kernel_probe("proc_open")

    assert result["seccomp"] == "2"
    assert result["rc"] == -1
    assert result["errno"] in {errno.EPERM, errno.EACCES}


def _run_kernel_probe(probe: str) -> dict[str, int | str]:
    env = os.environ.copy()
    env["NM_KERNEL_PROBE"] = probe
    proc = subprocess.run(
        [sys.executable, "-c", _KERNEL_PROBE_SCRIPT],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


_KERNEL_PROBE_SCRIPT = textwrap.dedent(
    r"""
    import ctypes
    import json
    import os
    import platform
    import sys

    from neuromouse_sandbox.kernel import apply_kernel_isolation

    SYSCALLS = {
        "x86_64": {
            "socket": 41,
            "ptrace": 101,
            "unshare": 272,
            "openat": 257,
        },
        "aarch64": {
            "socket": 198,
            "ptrace": 117,
            "unshare": 97,
            "openat": 56,
        },
    }

    probe = os.environ["NM_KERNEL_PROBE"]
    arch = platform.machine()
    if arch not in SYSCALLS:
        print(json.dumps({"skip": f"unsupported Linux arch: {arch}"}))
        raise SystemExit(0)

    apply_kernel_isolation(mode="required", phase="loader")
    with open("/proc/self/status", encoding="utf-8") as handle:
        seccomp = next(
            line.split(":", 1)[1].strip()
            for line in handle
            if line.startswith("Seccomp:")
        )
    if probe == "proc_open":
        from neuromouse_sandbox.kernel import apply_kernel_filesystem_policy

        apply_kernel_filesystem_policy(
            mode="required",
            read_allow_prefixes=(sys.base_prefix, sys.prefix, sys.exec_prefix, os.getcwd()),
            write_allow_prefixes=(os.getcwd(),),
        )

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    syscalls = SYSCALLS[arch]

    ctypes.set_errno(0)
    if probe == "socket":
        rc = libc.syscall(
            ctypes.c_long(syscalls["socket"]),
            ctypes.c_int(2),  # AF_INET
            ctypes.c_int(1),  # SOCK_STREAM
            ctypes.c_int(0),
        )
    elif probe == "ptrace":
        rc = libc.syscall(
            ctypes.c_long(syscalls["ptrace"]),
            ctypes.c_long(0),  # PTRACE_TRACEME
            ctypes.c_long(0),
            ctypes.c_void_p(),
            ctypes.c_void_p(),
        )
    elif probe == "unshare":
        rc = libc.syscall(
            ctypes.c_long(syscalls["unshare"]),
            ctypes.c_long(0x40000000),  # CLONE_NEWNET
        )
    elif probe == "proc_open":
        rc = libc.syscall(
            ctypes.c_long(syscalls["openat"]),
            ctypes.c_int(-100),  # AT_FDCWD
            ctypes.c_char_p(b"/proc/self/environ"),
            ctypes.c_int(os.O_RDONLY),
            ctypes.c_int(0),
        )
        if rc >= 0:
            os.close(rc)
    else:
        raise AssertionError(probe)

    print(json.dumps({"seccomp": seccomp, "rc": int(rc), "errno": ctypes.get_errno()}))
    """
)
