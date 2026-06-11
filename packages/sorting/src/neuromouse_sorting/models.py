from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, SupportsFloat, SupportsIndex


@dataclass(frozen=True)
class MEARecording:
    channels: Sequence[str]
    sampling_rate_hz: float
    traces: Sequence[Sequence[float]]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        channels = tuple(_clean_name(channel, "channel") for channel in self.channels)
        if not channels:
            raise ValueError("MEARecording.channels must contain at least one channel")
        if len(set(channels)) != len(channels):
            raise ValueError("MEARecording.channels must be unique")

        sampling_rate_hz = float(self.sampling_rate_hz)
        if not math.isfinite(sampling_rate_hz) or sampling_rate_hz <= 0:
            raise ValueError("MEARecording.sampling_rate_hz must be positive and finite")

        traces = tuple(
            tuple(_finite_float(sample, "trace sample") for sample in row)
            for row in self.traces
        )
        if len(traces) != len(channels):
            raise ValueError("MEARecording.traces must have one row per channel")
        lengths = {len(row) for row in traces}
        if lengths == {0}:
            raise ValueError("MEARecording.traces rows must not be empty")
        if len(lengths) != 1:
            raise ValueError("MEARecording.traces rows must have equal sample counts")

        object.__setattr__(self, "channels", channels)
        object.__setattr__(self, "sampling_rate_hz", sampling_rate_hz)
        object.__setattr__(self, "traces", traces)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def n_channels(self) -> int:
        return len(self.channels)

    @property
    def n_samples(self) -> int:
        return len(self.traces[0])


@dataclass(frozen=True)
class SortedUnit:
    unit_id: str
    channel: str
    spike_sample_indexes: Sequence[int]
    spike_times_sec: Sequence[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unit_id = _clean_name(self.unit_id, "unit_id")
        channel = _clean_name(self.channel, "channel")
        sample_indexes = tuple(
            _non_negative_int(index, "spike_sample_indexes")
            for index in self.spike_sample_indexes
        )
        spike_times = tuple(_finite_float(time, "spike_times_sec") for time in self.spike_times_sec)
        if len(sample_indexes) != len(spike_times):
            raise ValueError("SortedUnit spike sample indexes and times must have equal lengths")

        object.__setattr__(self, "unit_id", unit_id)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "spike_sample_indexes", sample_indexes)
        object.__setattr__(self, "spike_times_sec", spike_times)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class SortingResult:
    units: Sequence[SortedUnit]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "units", tuple(self.units))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class OutputField:
    path: str
    description: str = ""
    unit: str | None = None


@dataclass(frozen=True)
class SorterOutputSpec:
    fields: tuple[OutputField, ...]


def _clean_name(value: object, label: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ValueError(f"{label} must be a non-empty string")
    return clean


def _finite_float(value: SupportsFloat | SupportsIndex | str, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _non_negative_int(value: int, label: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must contain non-negative integers")
    return value
