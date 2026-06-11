from __future__ import annotations

import random

from neuromouse_sorting import MEARecording, SpikeSorterRegistry
from neuromouse_sorting.threshold import ThresholdSorterParams, threshold_sorter

KNOWN_SPIKES = {
    "MEA-1": (100, 250, 400),
    "MEA-2": (175, 300),
}


def seeded_synthetic_recording() -> MEARecording:
    rng = random.Random(8675309)
    sample_count = 512
    traces: list[tuple[float, ...]] = []
    for channel in ("MEA-1", "MEA-2"):
        samples = [rng.uniform(-0.12, 0.12) for _ in range(sample_count)]
        for spike_index in KNOWN_SPIKES[channel]:
            samples[spike_index - 1] -= 2.5
            samples[spike_index] -= 9.0
            samples[spike_index + 1] -= 2.5
        traces.append(tuple(samples))
    return MEARecording(
        channels=("MEA-1", "MEA-2"),
        sampling_rate_hz=1_000.0,
        traces=tuple(traces),
        metadata={"fixture": "seeded-threshold-recovery", "seed": 8675309},
    )


def test_threshold_sorter_recovers_seeded_synthetic_spikes_within_tolerance() -> None:
    registry = SpikeSorterRegistry()
    registry.register(threshold_sorter)
    params = ThresholdSorterParams(threshold=5.0, polarity="negative", refractory_ms=2.0)

    run = registry.run("threshold", seeded_synthetic_recording(), params=params)

    units_by_channel = {unit.channel: unit for unit in run.result.units}
    recovered = 0
    false_positives = 0
    for channel, expected_indexes in KNOWN_SPIKES.items():
        detected = units_by_channel[channel].spike_sample_indexes
        for expected in expected_indexes:
            assert any(abs(actual - expected) <= 1 for actual in detected)
            recovered += 1
        false_positives += sum(
            1
            for actual in detected
            if not any(abs(actual - expected) <= 1 for expected in expected_indexes)
        )

    assert recovered == 5
    assert false_positives == 0
    assert run.result.metadata["n_units"] == 2
    assert run.result.metadata["n_spikes"] == 5
    assert run.result.metadata["detection_threshold"] == 5.0
