"""Shared fixtures for the sandbox test-suite.

``ROOT`` is the repository root (four parents up from this file), which is where
the bundled MEA reference methods and the golden datasets live. Helpers are
exposed as fixtures (rather than importable module symbols) so the suite follows
pytest's conftest convention and type-checks cleanly.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from neuromouse_sandbox import MethodRef, SandboxLimits

ROOT = Path(__file__).resolve().parents[3]
PROBES = Path(__file__).resolve().parent / "probes"
GOLDEN_MEA = ROOT / "datasets" / "golden" / "mea_synthetic.json"
SPIKE_DETECT_PATH = ROOT / "methods" / "spike_detect.py"
GOLDEN_GROUND_TRUTH_SPIKES = 57


@pytest.fixture
def probe_ref() -> Callable[[str], MethodRef]:
    """Factory returning a :class:`MethodRef` for a probe module by name."""

    def _make(name: str) -> MethodRef:
        return MethodRef(kind="file", path=str(PROBES / f"{name}.py"), attr="method")

    return _make


@pytest.fixture
def spike_detect_ref() -> MethodRef:
    return MethodRef(kind="file", path=str(SPIKE_DETECT_PATH), attr="method")


@pytest.fixture
def golden_spike_count() -> int:
    return GOLDEN_GROUND_TRUTH_SPIKES


@pytest.fixture(scope="session")
def golden_dataset() -> dict:
    return json.loads(GOLDEN_MEA.read_text(encoding="utf-8"))


@pytest.fixture
def fast_limits() -> SandboxLimits:
    """Tight limits so hostile probes resolve quickly without ever threatening
    the host: short wall-clock, low CPU, modest memory, low process ceiling."""

    return SandboxLimits(
        wall_clock_sec=6.0,
        cpu_sec=4,
        memory_bytes=512 * 1024 * 1024,
        max_output_bytes=32 * 1024 * 1024,
        max_processes=64,
        max_open_files=128,
    )
