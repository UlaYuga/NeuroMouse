"""Legitimate methods must run correctly *through* the sandbox boundary.

The headline guarantee: ``spike_detect`` still recovers 57/57 injected
ground-truth spikes on the 1024-channel golden fixture when executed in the
isolated subprocess — isolation must not change the science.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import pytest

from neuromouse_sandbox import MethodRef, SandboxLimits, describe_in_sandbox, run_in_sandbox
from neuromouse_sandbox.runner import SandboxMethodError

ROOT = Path(__file__).resolve().parents[3]
SPIKE_MATCH_TOLERANCE_SEC = 0.0015


def test_legit_method_returns_result_through_sandbox(
    probe_ref: Callable[[str], MethodRef], fast_limits: SandboxLimits
) -> None:
    result = run_in_sandbox(
        probe_ref("legit_echo"),
        dataset=None,
        params={},
        limits=fast_limits,
        output_fields=("echo.ok",),
    )
    assert result == {"echo": {"ok": True, "n": 42, "items": [1, 2, 3]}}


def test_missing_output_field_is_graceful_method_error(
    probe_ref: Callable[[str], MethodRef], fast_limits: SandboxLimits
) -> None:
    with pytest.raises(SandboxMethodError):
        run_in_sandbox(
            probe_ref("legit_echo"),
            dataset=None,
            params={},
            limits=fast_limits,
            output_fields=("echo.not_present",),
        )


def test_spike_detect_recovers_57_of_57_through_sandbox(
    spike_detect_ref: MethodRef, golden_dataset: dict, golden_spike_count: int
) -> None:
    result = run_in_sandbox(
        spike_detect_ref,
        dataset=golden_dataset,
        params={"polarity": "positive"},
        limits=SandboxLimits(wall_clock_sec=30.0, cpu_sec=25),
        required_inputs=("meta.channels", "mea.sampling_rate_hz", "mea.traces"),
        output_fields=("spike_detect.spikes", "spike_detect.rates", "spike_detect.summary"),
    )
    payload = result["spike_detect"]
    assert payload["summary"]["total_spikes"] == golden_spike_count

    detected = {row["electrode"]: row["spike_times_sec"] for row in payload["spikes"]}
    matched, total = _match_spike_recovery(detected, golden_dataset)
    assert total == golden_spike_count
    assert matched == golden_spike_count


def test_describe_template_method_returns_dataclass_params_schema(
    fast_limits: SandboxLimits,
) -> None:
    metadata = describe_in_sandbox(
        MethodRef(
            kind="file",
            path=str(ROOT / "packages" / "sdk" / "templates" / "method_template.py"),
            attr="method",
        ),
        limits=fast_limits,
    )

    properties = metadata["params_schema"]["properties"]
    assert properties["threshold"]["default"] == 0.5
    assert properties["threshold"]["type"] == "number"


def _match_spike_recovery(detected: dict, golden: dict) -> tuple[int, int]:
    sampling_rate_hz = golden["mea"]["sampling_rate_hz"]
    expected: dict[str, list[float]] = defaultdict(list)
    for event in golden["spike_ground_truth"]["events"]:
        expected[event["channel"]].append(event["sample_index"] / sampling_rate_hz)

    matched = 0
    total = 0
    for channel, expected_times in expected.items():
        remaining = list(detected.get(channel, []))
        for expected_time in expected_times:
            total += 1
            if not remaining:
                continue
            closest = min(remaining, key=lambda actual: abs(actual - expected_time))
            if abs(closest - expected_time) <= SPIKE_MATCH_TOLERANCE_SEC:
                matched += 1
                remaining.remove(closest)
    return matched, total
