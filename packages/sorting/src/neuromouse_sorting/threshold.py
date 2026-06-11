from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from neuromouse_sorting.models import (
    MEARecording,
    OutputField,
    SortedUnit,
    SorterOutputSpec,
    SortingResult,
)

Polarity = Literal["negative", "positive", "both"]


@dataclass(frozen=True)
class ThresholdSorterParams:
    threshold: float = 5.0
    polarity: Polarity = "negative"
    refractory_ms: float = 1.0


class ThresholdSorter:
    name = "threshold"
    version = "0.1.0"
    params_type = ThresholdSorterParams
    output = SorterOutputSpec(
        fields=(
            OutputField("units", "Detected units with spike trains"),
            OutputField("metadata.sorter", "Sorter implementation name"),
            OutputField("metadata.version", "Sorter implementation version"),
            OutputField("metadata.n_units", "Number of units with at least one spike"),
            OutputField("metadata.n_spikes", "Total detected spike count"),
            OutputField("metadata.detection_threshold", "Detection threshold"),
            OutputField("metadata.polarity", "Detection polarity"),
            OutputField("metadata.refractory_ms", "Refractory window in milliseconds"),
        )
    )

    def sort(self, recording: MEARecording, params: ThresholdSorterParams) -> SortingResult:
        _validate_params(params)
        refractory_samples = max(
            1,
            int(round((params.refractory_ms / 1_000.0) * recording.sampling_rate_hz)),
        )
        units: list[SortedUnit] = []
        for channel, samples in zip(recording.channels, recording.traces, strict=True):
            indexes = _detect_spikes(samples, params, refractory_samples=refractory_samples)
            if not indexes:
                continue
            units.append(
                SortedUnit(
                    unit_id=f"{channel}:threshold",
                    channel=channel,
                    spike_sample_indexes=indexes,
                    spike_times_sec=tuple(index / recording.sampling_rate_hz for index in indexes),
                    metadata={
                        "sorter": self.name,
                        "threshold": params.threshold,
                        "polarity": params.polarity,
                    },
                )
            )

        n_spikes = sum(len(unit.spike_sample_indexes) for unit in units)
        return SortingResult(
            units=tuple(units),
            metadata={
                "sorter": self.name,
                "version": self.version,
                "n_units": len(units),
                "n_spikes": n_spikes,
                "detection_threshold": params.threshold,
                "polarity": params.polarity,
                "refractory_ms": params.refractory_ms,
            },
        )


threshold_sorter = ThresholdSorter()


def _validate_params(params: ThresholdSorterParams) -> None:
    if not math.isfinite(params.threshold) or params.threshold <= 0:
        raise ValueError("threshold must be a positive finite number")
    if params.polarity not in {"negative", "positive", "both"}:
        raise ValueError("polarity must be 'negative', 'positive', or 'both'")
    if not math.isfinite(params.refractory_ms) or params.refractory_ms < 0:
        raise ValueError("refractory_ms must be a non-negative finite number")


def _detect_spikes(
    samples: Sequence[float],
    params: ThresholdSorterParams,
    *,
    refractory_samples: int,
) -> tuple[int, ...]:
    indexes: list[int] = []
    last_index = -refractory_samples
    sample_index = 0
    while sample_index < len(samples):
        if not _above_threshold(samples[sample_index], params):
            sample_index += 1
            continue

        start = sample_index
        while sample_index < len(samples) and _above_threshold(samples[sample_index], params):
            sample_index += 1
        stop = sample_index
        peak_index = _peak_index(samples, start=start, stop=stop, polarity=params.polarity)
        if peak_index - last_index >= refractory_samples:
            indexes.append(peak_index)
            last_index = peak_index
    return tuple(indexes)


def _above_threshold(sample: float, params: ThresholdSorterParams) -> bool:
    if params.polarity == "negative":
        return sample <= -params.threshold
    if params.polarity == "positive":
        return sample >= params.threshold
    return abs(sample) >= params.threshold


def _peak_index(samples: Sequence[float], *, start: int, stop: int, polarity: Polarity) -> int:
    segment = range(start, stop)
    if polarity == "negative":
        return min(segment, key=lambda index: samples[index])
    if polarity == "positive":
        return max(segment, key=lambda index: samples[index])
    return max(segment, key=lambda index: abs(samples[index]))
