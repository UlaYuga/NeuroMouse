from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from neuromouse_sdk import OutputField, OutputSpec, PanelSpec

if TYPE_CHECKING:
    from neuromouse_contract import Dataset


@dataclass(frozen=True)
class ElectrodeConnectivityParams:
    """Parameters for this reference cross-correlation MEA connectivity template."""

    bin_size_ms: float = 5.0
    max_lag_ms: float = 20.0


class ElectrodeConnectivity:
    """Reference pairwise spike-train cross-correlation matrix.

    This template consumes per-electrode spike times from a detector or sorter seam,
    bins them, and records the strongest normalized cross-correlation per electrode
    pair. It is a compact reference panel producer, not an inference of causal
    connectivity.
    """

    name = "electrode_connectivity"
    version = "0.0.0"
    params_type = ElectrodeConnectivityParams
    required_inputs = ("meta.channels", "mea.spikes", "mea.duration_sec")
    output = OutputSpec(
        fields=(
            OutputField("electrode_connectivity.channels", description="Matrix channel order"),
            OutputField(
                "electrode_connectivity.matrix",
                description="Symmetric pairwise normalized cross-correlation matrix",
            ),
            OutputField("electrode_connectivity.links", description="Pairwise scores and lags"),
            OutputField("electrode_connectivity.summary", description="Strongest-pair summary"),
        ),
        panel=PanelSpec(
            id="electrode_connectivity_matrix",
            title="Electrode Connectivity Matrix",
            kind="matrix",
            field="electrode_connectivity.matrix",
        ),
    )

    def compute(self, dataset: Dataset, params: ElectrodeConnectivityParams) -> dict[str, Any]:
        channels = list(dataset.meta.channels)
        spikes = _spike_mapping(_mea_value(dataset, "spikes"), channels)
        duration_sec = _positive_float(_mea_value(dataset, "duration_sec"), "mea.duration_sec")
        bin_size_sec = _positive_float(params.bin_size_ms, "bin_size_ms") / 1000.0
        max_lag_sec = max(0.0, float(params.max_lag_ms) / 1000.0)
        if not math.isfinite(max_lag_sec):
            raise ValueError("max_lag_ms must be finite")

        bin_count = max(1, math.ceil(duration_sec / bin_size_sec))
        lag_bins = int(round(max_lag_sec / bin_size_sec))
        binned = [
            _bin_spikes(spikes[channel], duration_sec, bin_size_sec, bin_count)
            for channel in channels
        ]
        matrix = [[0.0 for _ in channels] for _ in channels]
        links: list[dict[str, Any]] = []
        strongest: dict[str, Any] | None = None
        strongest_rank: tuple[float, int, int, int] | None = None

        for row_index, source in enumerate(channels):
            matrix[row_index][row_index] = 1.0
            for column_index in range(row_index + 1, len(channels)):
                target = channels[column_index]
                score, lag, support = _best_lagged_score(
                    binned[row_index],
                    binned[column_index],
                    lag_bins,
                )
                rounded_score = round(score, 6)
                lag_ms = round(lag * bin_size_sec * 1000.0, 6)
                matrix[row_index][column_index] = rounded_score
                matrix[column_index][row_index] = rounded_score
                link = {
                    "source": source,
                    "target": target,
                    "score": rounded_score,
                    "lag_ms": lag_ms,
                    "support": support,
                }
                links.append(link)
                rank = (rounded_score, support, -row_index, -column_index)
                if strongest_rank is None or rank > strongest_rank:
                    strongest_rank = rank
                    strongest = link

        if strongest is None:
            strongest_pair = {"source": "", "target": "", "score": 0.0, "lag_ms": 0.0}
        else:
            strongest_pair = {
                "source": strongest["source"],
                "target": strongest["target"],
                "score": strongest["score"],
                "lag_ms": strongest["lag_ms"],
            }

        return {
            "electrode_connectivity": {
                "channels": channels,
                "matrix": matrix,
                "links": links,
                "summary": {
                    "method_note": "reference template over binned spike trains",
                    "strongest_pair": strongest_pair,
                    "bin_size_ms": params.bin_size_ms,
                    "max_lag_ms": params.max_lag_ms,
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


def _bin_spikes(
    spike_times: list[float],
    duration_sec: float,
    bin_size_sec: float,
    bin_count: int,
) -> list[int]:
    bins = [0 for _ in range(bin_count)]
    for spike_time in spike_times:
        if 0.0 <= spike_time <= duration_sec:
            index = min(int(spike_time / bin_size_sec), bin_count - 1)
            bins[index] += 1
    return bins


def _best_lagged_score(left: list[int], right: list[int], lag_bins: int) -> tuple[float, int, int]:
    best_score = -1.0
    best_lag = 0
    best_support = 0
    for lag in range(-lag_bins, lag_bins + 1):
        score, support = _lagged_cosine(left, right, lag)
        rank = (score, support, -abs(lag))
        best_rank = (best_score, best_support, -abs(best_lag))
        if rank > best_rank:
            best_score = score
            best_lag = lag
            best_support = support
    return max(0.0, best_score), best_lag, best_support


def _lagged_cosine(left: list[int], right: list[int], lag: int) -> tuple[float, int]:
    if lag >= 0:
        left_window = left[lag:]
        right_window = right[: len(right) - lag] if lag else right
    else:
        offset = -lag
        left_window = left[: len(left) - offset]
        right_window = right[offset:]
    if not left_window or not right_window:
        return 0.0, 0
    dot = sum(a * b for a, b in zip(left_window, right_window, strict=True))
    left_energy = sum(a * a for a in left_window)
    right_energy = sum(b * b for b in right_window)
    if left_energy == 0 or right_energy == 0:
        return 0.0, 0
    return dot / math.sqrt(left_energy * right_energy), dot


method = ElectrodeConnectivity()


__all__ = ["ElectrodeConnectivity", "ElectrodeConnectivityParams", "method", "register"]
