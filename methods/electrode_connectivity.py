from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

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
        binned = _binned_matrix(spikes, channels, duration_sec, bin_size_sec, bin_count)

        matrix, links, strongest = _connectivity(
            binned,
            channels,
            lag_bins=lag_bins,
            bin_size_sec=bin_size_sec,
        )

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


def _binned_matrix(
    spikes: dict[str, list[float]],
    channels: list[str],
    duration_sec: float,
    bin_size_sec: float,
    bin_count: int,
) -> np.ndarray:
    """Channel-major spike-count matrix, bit-identical to per-channel ``_bin_spikes``."""
    binned = np.zeros((len(channels), bin_count), dtype=np.int64)
    last_bin = bin_count - 1
    for row_index, channel in enumerate(channels):
        spike_times = spikes[channel]
        if not spike_times:
            continue
        times = np.asarray(spike_times, dtype=np.float64)
        in_range = times[(times >= 0.0) & (times <= duration_sec)]
        if in_range.size == 0:
            continue
        indices = np.minimum((in_range / bin_size_sec).astype(np.int64), last_bin)
        np.add.at(binned[row_index], indices, 1)
    return binned


def _connectivity(
    binned: np.ndarray,
    channels: list[str],
    *,
    lag_bins: int,
    bin_size_sec: float,
) -> tuple[list[list[float]], list[dict[str, Any]], dict[str, Any] | None]:
    """Vectorized pairwise lagged cosine matching the reference per-pair semantics.

    For each lag the normalized cross-correlation between every channel pair is computed
    with one matmul; the best lag per pair is selected with the reference tie-break
    ``(score, support, -abs(lag))`` evaluated in ascending lag order.
    """
    channel_count = len(channels)
    bin_count = binned.shape[1]
    binned_f = binned.astype(np.float64)

    # Per-cell running best across lags. best_score starts below any real score (>= 0)
    # so the first lag always wins, exactly like the reference loop (init -1.0).
    best_score = np.full((channel_count, channel_count), -1.0, dtype=np.float64)
    best_support = np.zeros((channel_count, channel_count), dtype=np.int64)
    best_lag = np.zeros((channel_count, channel_count), dtype=np.int64)
    best_abs_lag = np.zeros((channel_count, channel_count), dtype=np.int64)

    for lag in range(-lag_bins, lag_bins + 1):
        if lag >= 0:
            left = binned_f[:, lag:]
            right = binned_f[:, : bin_count - lag]
        else:
            offset = -lag
            left = binned_f[:, : bin_count - offset]
            right = binned_f[:, offset:]

        width = left.shape[1]
        if width == 0:
            # Empty window -> reference returns (0.0, 0) for every pair.
            score = np.zeros((channel_count, channel_count), dtype=np.float64)
            support = np.zeros((channel_count, channel_count), dtype=np.int64)
        else:
            dot = left @ right.T  # (C, C): dot[i, j] = sum_k left[i, k] * right[j, k]
            left_energy = np.einsum("ij,ij->i", left, left)
            right_energy = np.einsum("ij,ij->i", right, right)
            denom = np.sqrt(left_energy[:, None] * right_energy[None, :])
            valid = (left_energy[:, None] > 0) & (right_energy[None, :] > 0)
            score = np.where(valid, dot / np.where(denom > 0, denom, 1.0), 0.0)
            support = np.where(valid, np.rint(dot).astype(np.int64), 0)

        abs_lag = abs(lag)
        better = (
            (score > best_score)
            | ((score == best_score) & (support > best_support))
            | (
                (score == best_score)
                & (support == best_support)
                & (abs_lag < best_abs_lag)
            )
        )
        best_score = np.where(better, score, best_score)
        best_support = np.where(better, support, best_support)
        best_lag = np.where(better, lag, best_lag)
        best_abs_lag = np.where(better, abs_lag, best_abs_lag)

    best_score = np.maximum(0.0, best_score)
    rounded = np.round(best_score, 6)
    lag_ms = np.round(best_lag.astype(np.float64) * bin_size_sec * 1000.0, 6)

    # Symmetric matrix from the upper triangle, diagonal forced to 1.0.
    matrix_array = np.zeros((channel_count, channel_count), dtype=np.float64)
    upper = np.triu_indices(channel_count, k=1)
    matrix_array[upper] = rounded[upper]
    matrix_array = matrix_array + matrix_array.T
    np.fill_diagonal(matrix_array, 1.0)
    matrix = matrix_array.tolist()

    rows = upper[0]
    cols = upper[1]
    scores_u = rounded[upper]
    supports_u = best_support[upper]
    lags_u = lag_ms[upper]

    # Strongest pair from the numpy arrays before materializing per-link dicts:
    # max by (score, support, -row, -column). ascending lexsort -> winner is index 0.
    strongest_index: int | None = None
    if scores_u.size:
        order = np.lexsort((cols, rows, -supports_u, -scores_u))
        strongest_index = int(order[0])

    source_names = [channels[row] for row in rows.tolist()]
    target_names = [channels[col] for col in cols.tolist()]
    links: list[dict[str, Any]] = [
        {
            "source": source,
            "target": target,
            "score": score,
            "lag_ms": lag,
            "support": support,
        }
        for source, target, score, lag, support in zip(
            source_names,
            target_names,
            scores_u.tolist(),
            lags_u.tolist(),
            supports_u.tolist(),
            strict=True,
        )
    ]

    strongest = None if strongest_index is None else links[strongest_index]
    return matrix, links, strongest


method = ElectrodeConnectivity()


__all__ = ["ElectrodeConnectivity", "ElectrodeConnectivityParams", "method", "register"]
