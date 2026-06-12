"""Ground-truth regression guards for the MEA reference methods on the 1024-channel
golden fixture.

These lock the *correctness* of ``spike_detect`` / ``network_burst`` /
``electrode_connectivity`` on ``datasets/golden/mea_synthetic.json`` so that the
performance optimisations in ``methods/*.py`` can never silently change the science.

The primary gate is ``spike_detect`` recovering 57/57 injected ground-truth spikes.
Burst/connectivity guards are computed from the *ground-truth* spike train (not from
``spike_detect`` output) so they stay stable independent of the detector implementation.

Not collected by the default ``uv run pytest`` (``bench`` is outside ``testpaths``);
run explicitly with ``uv run pytest bench/``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_MEA = ROOT / "datasets" / "golden" / "mea_synthetic.json"
SPIKE_MATCH_TOLERANCE_SEC = 0.0015

# Reference values captured from the reference (pre-optimisation) implementations.
GOLDEN_GROUND_TRUTH_SPIKES = 57
BURST_REFERENCE = {"burst_count": 1, "total_spikes": 57, "timeline_len": 7}
CONNECTIVITY_REFERENCE = {
    "strongest_source": "MEA-0098",
    "strongest_target": "MEA-0278",
    "strongest_score": 1.0,
    "strongest_lag_ms": 0.0,
    "matrix_checksum": 1822.442298,
    "n_links": 523776,
    "positive_links": 496,
}


def _load_method(name: str) -> Any:
    path = ROOT / "methods" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"nm_bench_method_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load method plugin at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_params(module: Any, params: dict[str, Any] | None) -> Any:
    from neuromouse_sdk import build_params

    return build_params(module.method.params_type, params)


def _golden() -> dict[str, Any]:
    return json.loads(GOLDEN_MEA.read_text(encoding="utf-8"))


def _trace_dataset(golden: dict[str, Any]) -> SimpleNamespace:
    mea = golden["mea"]
    traces = mea["traces"]
    duration_sec = len(traces[0]) / mea["sampling_rate_hz"]
    return SimpleNamespace(
        meta=SimpleNamespace(channels=list(golden["meta"]["channels"])),
        mea={
            "sampling_rate_hz": mea["sampling_rate_hz"],
            "traces": traces,
            "duration_sec": duration_sec,
        },
    )


def _ground_truth_spike_dataset(golden: dict[str, Any]) -> SimpleNamespace:
    mea = golden["mea"]
    sampling_rate_hz = mea["sampling_rate_hz"]
    duration_sec = len(mea["traces"][0]) / sampling_rate_hz
    channels = list(golden["meta"]["channels"])
    per_channel: dict[str, list[float]] = defaultdict(list)
    for event in golden["spike_ground_truth"]["events"]:
        per_channel[event["channel"]].append(event["sample_index"] / sampling_rate_hz)
    spikes = {channel: sorted(per_channel.get(channel, [])) for channel in channels}
    return SimpleNamespace(
        meta=SimpleNamespace(channels=channels),
        mea={"spikes": spikes, "duration_sec": duration_sec},
    )


def _match_spike_recovery(
    detected: dict[str, list[float]],
    golden: dict[str, Any],
) -> tuple[int, int, float]:
    sampling_rate_hz = golden["mea"]["sampling_rate_hz"]
    expected: dict[str, list[float]] = defaultdict(list)
    for event in golden["spike_ground_truth"]["events"]:
        expected[event["channel"]].append(event["sample_index"] / sampling_rate_hz)

    matched = 0
    total = 0
    max_abs_error = 0.0
    for channel, expected_times in expected.items():
        remaining = list(detected.get(channel, []))
        for expected_time in expected_times:
            total += 1
            if not remaining:
                continue
            closest = min(remaining, key=lambda actual: abs(actual - expected_time))
            error = abs(closest - expected_time)
            if error <= SPIKE_MATCH_TOLERANCE_SEC:
                matched += 1
                remaining.remove(closest)
                max_abs_error = max(max_abs_error, error)
    return matched, total, max_abs_error


def test_spike_detect_recovers_57_of_57_golden_ground_truth_spikes() -> None:
    golden = _golden()
    assert golden["spike_ground_truth"]["n_events"] == GOLDEN_GROUND_TRUTH_SPIKES

    spike_detect = _load_method("spike_detect")
    dataset = _trace_dataset(golden)
    result = spike_detect.method.compute(
        dataset,
        _build_params(spike_detect, {"polarity": "positive"}),
    )["spike_detect"]

    detected = {row["electrode"]: row["spike_times_sec"] for row in result["spikes"]}
    matched, total, max_abs_error = _match_spike_recovery(detected, golden)

    assert total == GOLDEN_GROUND_TRUTH_SPIKES
    assert matched == GOLDEN_GROUND_TRUTH_SPIKES
    assert result["summary"]["total_spikes"] == GOLDEN_GROUND_TRUTH_SPIKES
    assert max_abs_error <= SPIKE_MATCH_TOLERANCE_SEC


def test_network_burst_pools_golden_ground_truth_into_reference_window() -> None:
    golden = _golden()
    network_burst = _load_method("network_burst")
    dataset = _ground_truth_spike_dataset(golden)

    result = network_burst.method.compute(
        dataset,
        _build_params(network_burst, {}),
    )["network_burst"]

    summary = result["summary"]
    assert summary["burst_count"] == BURST_REFERENCE["burst_count"]
    assert summary["total_spikes"] == BURST_REFERENCE["total_spikes"]
    assert len(result["timeline"]) == BURST_REFERENCE["timeline_len"]
    assert len(result["bursts"]) == BURST_REFERENCE["burst_count"]


def test_electrode_connectivity_matches_reference_on_golden_ground_truth() -> None:
    golden = _golden()
    electrode_connectivity = _load_method("electrode_connectivity")
    dataset = _ground_truth_spike_dataset(golden)

    result = electrode_connectivity.method.compute(
        dataset,
        _build_params(electrode_connectivity, {}),
    )["electrode_connectivity"]

    matrix = result["matrix"]
    channels = result["channels"]
    assert len(matrix) == len(channels)
    # Diagonal, symmetry and range invariants.
    for row_index, row in enumerate(matrix):
        assert len(row) == len(channels)
        assert row[row_index] == pytest.approx(1.0)
    assert all(0.0 <= value <= 1.0 for row in matrix for value in row)

    checksum = round(sum(value for row in matrix for value in row), 6)
    assert checksum == pytest.approx(CONNECTIVITY_REFERENCE["matrix_checksum"], abs=1e-3)
    assert len(result["links"]) == CONNECTIVITY_REFERENCE["n_links"]
    positive_links = sum(1 for link in result["links"] if link["score"] > 0)
    assert positive_links == CONNECTIVITY_REFERENCE["positive_links"]

    strongest = result["summary"]["strongest_pair"]
    assert strongest["source"] == CONNECTIVITY_REFERENCE["strongest_source"]
    assert strongest["target"] == CONNECTIVITY_REFERENCE["strongest_target"]
    assert strongest["score"] == pytest.approx(CONNECTIVITY_REFERENCE["strongest_score"])
    assert strongest["lag_ms"] == pytest.approx(CONNECTIVITY_REFERENCE["strongest_lag_ms"])


def test_connectivity_matrix_is_symmetric_on_golden_ground_truth() -> None:
    golden = _golden()
    electrode_connectivity = _load_method("electrode_connectivity")
    dataset = _ground_truth_spike_dataset(golden)

    matrix = electrode_connectivity.method.compute(
        dataset,
        _build_params(electrode_connectivity, {}),
    )["electrode_connectivity"]["matrix"]

    # Spot-check symmetry on a deterministic stride to keep the assertion O(C).
    size = len(matrix)
    for index in range(0, size, 37):
        for offset in range(1, 5):
            other = (index + offset * 53) % size
            assert matrix[index][other] == pytest.approx(matrix[other][index])
