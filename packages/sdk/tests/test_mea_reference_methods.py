from __future__ import annotations

import importlib.util
import random
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from neuromouse_sdk import PanelSpec, build_params

SAMPLING_RATE_HZ = 5_000.0
DURATION_SEC = 0.9
CHANNELS = ("E01", "E02", "E03", "E04")
GROUND_TRUTH_SPIKES = {
    "E01": [0.100, 0.200, 0.350, 0.620, 0.800],
    "E02": [0.101, 0.201, 0.351, 0.621, 0.801],
    "E03": [0.204, 0.626],
    "E04": [0.207, 0.633],
}
INJECTED_BURST_STARTS = (0.200, 0.620)
ROOT = Path(__file__).resolve().parents[3]


class LocalRegistry:
    def __init__(self) -> None:
        self.methods: dict[str, Any] = {}

    def register(self, method: Any) -> Any:
        if method.name in self.methods:
            raise ValueError(f"method already registered: {method.name}")
        self.methods[method.name] = method
        return method


def seeded_mea_fixture() -> Any:
    rng = random.Random(20260611)
    n_samples = int(SAMPLING_RATE_HZ * DURATION_SEC)
    traces = [
        [rng.gauss(0.0, 0.012) for _ in range(n_samples)]
        for _ in CHANNELS
    ]
    waveform = [0.0, -0.12, -0.55, -1.15, -0.55, -0.12, 0.0]
    half_width = len(waveform) // 2

    for channel_index, channel in enumerate(CHANNELS):
        for spike_time in GROUND_TRUTH_SPIKES[channel]:
            center = int(round(spike_time * SAMPLING_RATE_HZ))
            left = center - half_width
            for sample_offset, amplitude in enumerate(waveform):
                traces[channel_index][left + sample_offset] += amplitude

    return SimpleNamespace(
        meta=SimpleNamespace(
            channels=list(CHANNELS),
            n_channels=len(CHANNELS),
            sampling_rate_analysis_hz=SAMPLING_RATE_HZ,
            source="seeded synthetic MEA fixture for reference method tests",
        ),
        welch_psd=SimpleNamespace(
            frequencies=[1.0, 2.0],
            psd=[[1.0, 1.0] for _ in CHANNELS],
        ),
        centroid=SimpleNamespace(
            time_relative=[0.0, DURATION_SEC],
            values=[[0.0, 0.0] for _ in CHANNELS],
        ),
        geometry=SimpleNamespace(time=[0.0, DURATION_SEC]),
        mea={
            "sampling_rate_hz": SAMPLING_RATE_HZ,
            "duration_sec": DURATION_SEC,
            "traces": traces,
            "spikes": GROUND_TRUTH_SPIKES,
        },
    )


def test_spike_detect_registers_and_recovers_injected_spikes() -> None:
    spike_detect = load_plugin("spike_detect")

    registry = LocalRegistry()
    registered = spike_detect.register(registry)

    result = run_method(spike_detect, seeded_mea_fixture())

    assert registered is spike_detect.method
    assert registry.methods["spike_detect"] is spike_detect.method
    assert spike_detect.method.output.panel == PanelSpec(
        id="spike_detect_rates",
        title="Spike Detect Firing Rates",
        kind="heatmap_table",
        field="spike_detect.rates",
    )
    assert all(has_field_path(result, field.path) for field in spike_detect.method.output.fields)

    rows = result["spike_detect"]["spikes"]
    detected = {row["electrode"]: row["spike_times_sec"] for row in rows}
    matched, total, max_abs_error = match_spikes(detected, GROUND_TRUTH_SPIKES)

    assert matched == total == 14
    assert max_abs_error <= 0.0015
    assert result["spike_detect"]["summary"]["total_spikes"] == 14
    assert {row["electrode"]: row["rate_hz"] for row in result["spike_detect"]["rates"]} == {
        "E01": pytest.approx(5 / DURATION_SEC),
        "E02": pytest.approx(5 / DURATION_SEC),
        "E03": pytest.approx(2 / DURATION_SEC),
        "E04": pytest.approx(2 / DURATION_SEC),
    }


def test_network_burst_registers_and_detects_injected_bursts() -> None:
    network_burst = load_plugin("network_burst")

    registry = LocalRegistry()
    registered = network_burst.register(registry)

    result = run_method(
        network_burst,
        seeded_mea_fixture(),
        params={"bin_size_ms": 10.0, "threshold_count": 3, "merge_gap_ms": 15.0},
    )

    assert registered is network_burst.method
    assert network_burst.method.output.panel == PanelSpec(
        id="network_burst_timeline",
        title="Network Burst Timeline",
        kind="timeline",
        field="network_burst.timeline",
    )
    bursts = result["network_burst"]["bursts"]
    assert len(bursts) == 2
    for burst, expected_start in zip(bursts, INJECTED_BURST_STARTS, strict=True):
        assert burst["start_sec"] == pytest.approx(expected_start, abs=0.010)
        assert burst["spike_count"] >= 3
    assert result["network_burst"]["summary"]["burst_count"] == 2
    assert any(row["in_burst"] for row in result["network_burst"]["timeline"])


def test_electrode_connectivity_registers_and_identifies_known_coupled_pair() -> None:
    electrode_connectivity = load_plugin("electrode_connectivity")

    registry = LocalRegistry()
    registered = electrode_connectivity.register(registry)

    result = run_method(
        electrode_connectivity,
        seeded_mea_fixture(),
        params={"bin_size_ms": 5.0, "max_lag_ms": 5.0},
    )

    assert registered is electrode_connectivity.method
    assert electrode_connectivity.method.output.panel == PanelSpec(
        id="electrode_connectivity_matrix",
        title="Electrode Connectivity Matrix",
        kind="matrix",
        field="electrode_connectivity.matrix",
    )
    matrix = result["electrode_connectivity"]["matrix"]
    assert len(matrix) == len(CHANNELS)
    for row_index, row in enumerate(matrix):
        assert len(row) == len(CHANNELS)
        assert row[row_index] == pytest.approx(1.0)
        for column_index, value in enumerate(row):
            assert value == pytest.approx(matrix[column_index][row_index])

    assert result["electrode_connectivity"]["summary"]["strongest_pair"] == {
        "source": "E01",
        "target": "E02",
        "score": pytest.approx(1.0),
        "lag_ms": pytest.approx(0.0),
    }


@given(
    threshold_k=st.floats(min_value=3.0, max_value=8.0, allow_nan=False, allow_infinity=False),
    refractory_ms=st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False),
    bin_size_ms=st.floats(min_value=5.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    threshold_count=st.integers(min_value=2, max_value=5),
    max_lag_ms=st.floats(min_value=0.0, max_value=15.0, allow_nan=False, allow_infinity=False),
)
@settings(
    max_examples=8,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_mea_method_params_property_keep_outputs_declared_and_well_formed(
    threshold_k: float,
    refractory_ms: float,
    bin_size_ms: float,
    threshold_count: int,
    max_lag_ms: float,
) -> None:
    electrode_connectivity = load_plugin("electrode_connectivity")
    network_burst = load_plugin("network_burst")
    spike_detect = load_plugin("spike_detect")

    dataset = seeded_mea_fixture()
    spike_result = run_method(
        spike_detect,
        dataset,
        params={"threshold_k": threshold_k, "refractory_ms": refractory_ms},
    )
    burst_result = run_method(
        network_burst,
        dataset,
        params={"bin_size_ms": bin_size_ms, "threshold_count": threshold_count},
    )
    connectivity_result = run_method(
        electrode_connectivity,
        dataset,
        params={"bin_size_ms": bin_size_ms, "max_lag_ms": max_lag_ms},
    )

    for plugin, result in (
        (spike_detect, spike_result),
        (network_burst, burst_result),
        (electrode_connectivity, connectivity_result),
    ):
        assert all(has_field_path(result, field.path) for field in plugin.method.output.fields)

    for row in spike_result["spike_detect"]["spikes"]:
        assert row["spike_times_sec"] == sorted(row["spike_times_sec"])
        assert row["spike_count"] == len(row["spike_times_sec"])
        assert row["rate_hz"] >= 0.0

    for burst in burst_result["network_burst"]["bursts"]:
        assert burst["start_sec"] < burst["end_sec"]
        assert burst["spike_count"] >= threshold_count

    matrix = connectivity_result["electrode_connectivity"]["matrix"]
    assert len(matrix) == len(CHANNELS)
    assert all(-1.0 <= value <= 1.0 for row in matrix for value in row)


def run_method(module: Any, dataset: Any, params: Mapping[str, Any] | None = None) -> Any:
    typed_params = build_params(module.method.params_type, params)
    return module.method.compute(dataset, typed_params)


def load_plugin(name: str) -> Any:
    path = ROOT / "methods" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"neuromouse_method_test_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load method plugin at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def has_field_path(value: Any, path: str) -> bool:
    current = value
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return False
            current = current[part]
            continue
        if not hasattr(current, part):
            return False
        current = getattr(current, part)
    return current is not None


def match_spikes(
    detected: Mapping[str, list[float]],
    expected: Mapping[str, list[float]],
) -> tuple[int, int, float]:
    matched = 0
    max_abs_error = 0.0
    total = sum(len(times) for times in expected.values())
    for channel, expected_times in expected.items():
        remaining = list(detected[channel])
        for expected_time in expected_times:
            closest = min(remaining, key=lambda actual: abs(actual - expected_time))
            remaining.remove(closest)
            error = abs(closest - expected_time)
            if error <= 0.0015:
                matched += 1
            max_abs_error = max(max_abs_error, error)
    return matched, total, max_abs_error
