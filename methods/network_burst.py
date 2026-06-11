from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from neuromouse_sdk import OutputField, OutputSpec, PanelSpec

if TYPE_CHECKING:
    from neuromouse_contract import Dataset


@dataclass(frozen=True)
class NetworkBurstParams:
    """Parameters for this reference binned population-burst MEA template."""

    bin_size_ms: float = 10.0
    threshold_count: int = 3
    merge_gap_ms: float = 20.0
    min_spikes: int = 1


class NetworkBurst:
    """Reference population burst detector for pooled MEA spike trains.

    This template consumes per-electrode spike times that can come from a sorter seam
    or a simple detector. It bins the pooled train, thresholds population count, and
    merges nearby active windows; it is not a full burst-analysis package.
    """

    name = "network_burst"
    version = "0.0.0"
    params_type = NetworkBurstParams
    required_inputs = ("meta.channels", "mea.spikes", "mea.duration_sec")
    output = OutputSpec(
        fields=(
            OutputField("network_burst.bursts", description="Merged population burst windows"),
            OutputField("network_burst.timeline", description="Binned population rate timeline"),
            OutputField("network_burst.summary", description="Burst detector settings and counts"),
        ),
        panel=PanelSpec(
            id="network_burst_timeline",
            title="Network Burst Timeline",
            kind="timeline",
            field="network_burst.timeline",
        ),
    )

    def compute(self, dataset: Dataset, params: NetworkBurstParams) -> dict[str, Any]:
        channels = list(dataset.meta.channels)
        spikes = _spike_mapping(_mea_value(dataset, "spikes"), channels)
        duration_sec = _positive_float(_mea_value(dataset, "duration_sec"), "mea.duration_sec")
        bin_size_sec = _positive_float(params.bin_size_ms, "bin_size_ms") / 1000.0
        threshold_count = _positive_int(params.threshold_count, "threshold_count")
        min_spikes = _positive_int(params.min_spikes, "min_spikes")
        merge_gap_sec = max(0.0, float(params.merge_gap_ms) / 1000.0)
        if not math.isfinite(merge_gap_sec):
            raise ValueError("merge_gap_ms must be finite")

        bins = max(1, math.ceil(duration_sec / bin_size_sec))
        counts = [0 for _ in range(bins)]
        pooled = sorted(time for times in spikes.values() for time in times)
        for spike_time in pooled:
            if 0.0 <= spike_time <= duration_sec:
                index = min(int(spike_time / bin_size_sec), bins - 1)
                counts[index] += 1

        raw_segments = _active_segments(counts, threshold_count)
        merged_segments = _merge_segments(raw_segments, bin_size_sec, merge_gap_sec)
        bursts = []
        burst_bins: set[int] = set()
        for start_bin, stop_bin in merged_segments:
            spike_count = sum(counts[start_bin:stop_bin])
            if spike_count < min_spikes:
                continue
            start_sec = start_bin * bin_size_sec
            end_sec = min(stop_bin * bin_size_sec, duration_sec)
            for bin_index in range(start_bin, stop_bin):
                burst_bins.add(bin_index)
            bursts.append(
                {
                    "start_sec": round(start_sec, 6),
                    "end_sec": round(end_sec, 6),
                    "duration_sec": round(end_sec - start_sec, 6),
                    "spike_count": spike_count,
                    "peak_rate_hz": max(counts[start_bin:stop_bin]) / bin_size_sec,
                }
            )

        timeline = [
            {
                "bin_start_sec": round(index * bin_size_sec, 6),
                "bin_end_sec": round(min((index + 1) * bin_size_sec, duration_sec), 6),
                "spike_count": count,
                "population_rate_hz": count / bin_size_sec,
                "in_burst": index in burst_bins,
            }
            for index, count in enumerate(counts)
        ]

        return {
            "network_burst": {
                "bursts": bursts,
                "timeline": timeline,
                "summary": {
                    "method_note": "reference template over pooled spike trains",
                    "burst_count": len(bursts),
                    "total_spikes": len(pooled),
                    "bin_size_ms": params.bin_size_ms,
                    "threshold_count": threshold_count,
                    "merge_gap_ms": params.merge_gap_ms,
                    "min_spikes": min_spikes,
                },
            }
        }


def register(registry: Any) -> Any:
    """Register this self-contained reference method with a caller-owned registry."""

    return registry.register(method)


def _mea_value(dataset: Any, key: str) -> Any:
    mea = getattr(dataset, "mea", None)
    if isinstance(mea, Mapping):
        return mea.get(key)
    if mea is not None and hasattr(mea, key):
        return getattr(mea, key)
    raise ValueError(f"dataset is missing mea.{key}")


def _positive_float(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return number


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    number = int(value)
    if number <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return number


def _spike_mapping(value: Any, channels: list[str]) -> dict[str, list[float]]:
    if isinstance(value, Mapping):
        return {
            channel: sorted(float(time) for time in value.get(channel, []))
            for channel in channels
        }
    if isinstance(value, list):
        rows: dict[str, list[float]] = {channel: [] for channel in channels}
        for row in value:
            if not isinstance(row, Mapping):
                raise ValueError("mea.spikes rows must be mappings")
            electrode = str(row.get("electrode"))
            if electrode in rows:
                rows[electrode] = sorted(float(time) for time in row.get("spike_times_sec", []))
        return rows
    raise ValueError("mea.spikes must be a mapping or spike row list")


def _active_segments(counts: list[int], threshold_count: int) -> list[tuple[int, int]]:
    segments = []
    index = 0
    while index < len(counts):
        if counts[index] < threshold_count:
            index += 1
            continue
        start = index
        while index < len(counts) and counts[index] >= threshold_count:
            index += 1
        segments.append((start, index))
    return segments


def _merge_segments(
    segments: list[tuple[int, int]],
    bin_size_sec: float,
    merge_gap_sec: float,
) -> list[tuple[int, int]]:
    if not segments:
        return []
    merged = [segments[0]]
    for start, stop in segments[1:]:
        previous_start, previous_stop = merged[-1]
        gap_sec = (start - previous_stop) * bin_size_sec
        if gap_sec <= merge_gap_sec:
            merged[-1] = (previous_start, stop)
        else:
            merged.append((start, stop))
    return merged


method = NetworkBurst()


__all__ = ["NetworkBurst", "NetworkBurstParams", "method", "register"]
