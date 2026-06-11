"""macOS startup guard for uv-managed native wheels.

This file is installed as a top-level module in site-packages. It is
intentionally limited to this repo's local `.venv`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_DISABLED_VALUES = {"0", "false", "no", "off"}
_PREWARM_IMPORTS = "import scipy.fft, jsonschema_rs, numpy"


def _running_in_repo_venv() -> bool:
    repo_root = Path(__file__).resolve().parent
    expected_venv = repo_root / ".venv"
    try:
        return Path(sys.prefix).resolve() == expected_venv.resolve()
    except OSError:
        return False


def _prewarm_enabled() -> bool:
    if sys.platform != "darwin":
        return False
    if os.environ.get("NEUROMOUSE_NATIVE_PREWARM_CHILD"):
        return False
    if os.environ.get("NEUROMOUSE_NATIVE_PREWARM", "1").strip().lower() in _DISABLED_VALUES:
        return False
    return _running_in_repo_venv()


def _disable_posix_spawn() -> None:
    # macOS 26.5 produced launched-but-not-started Node children from pytest's
    # Python subprocess calls. Fork/exec is slower but avoids that test-run stall.
    if sys.platform == "darwin" and hasattr(subprocess, "_USE_POSIX_SPAWN"):
        subprocess._USE_POSIX_SPAWN = False
    if sys.platform == "darwin" and hasattr(subprocess, "_USE_VFORK"):
        subprocess._USE_VFORK = False


def _prewarm_native_imports() -> None:
    attempts = int(os.environ.get("NEUROMOUSE_NATIVE_PREWARM_ATTEMPTS", "4"))
    timeout = float(os.environ.get("NEUROMOUSE_NATIVE_PREWARM_TIMEOUT", "8"))
    env = os.environ.copy()
    env["NEUROMOUSE_NATIVE_PREWARM_CHILD"] = "1"
    env.pop("PYTHONPATH", None)

    for _ in range(attempts):
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", _PREWARM_IMPORTS],
                check=False,
                env=env,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            continue
        if completed.returncode == 0:
            return

    raise RuntimeError(
        f"native import prewarm failed after {attempts} attempts of {timeout:.1f}s"
    )


_disable_posix_spawn()
if _prewarm_enabled():
    _prewarm_native_imports()
