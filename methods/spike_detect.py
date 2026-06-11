from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from neuromouse_sdk import OutputField, OutputSpec, PanelSpec

if TYPE_CHECKING:
    from neuromouse_contract import Dataset


@dataclass(frozen=True)
class SpikeDetectParams:
    """Parameters for this reference threshold-crossing MEA template."""

    threshold_k: float = 5.0
    bandpass_low_hz: float = 300.0
    bandpass_high_hz: float = 3000.0
    refractory_ms: float = 1.0
    polarity: str = "negative"


class SpikeDetect:
    """Reference MEA multi-unit threshold detector, not a full spike sorter.

    This template demonstrates the Method protocol on wetware/MEA-like raw traces:
    simple band-pass filtering, K x RMS noise thresholding, and per-electrode
    threshold-crossing times/rates. Unit identity, clustering, and curation belong
    in the sorter seam upstream of this reference method.
    """

    name = "spike_detect"
    version = "0.0.0"
    params_type = SpikeDetectParams
    required_inputs = ("meta.channels", "mea.sampling_rate_hz", "mea.traces")
    output = OutputSpec(
        fields=(
            OutputField(
                "spike_detect.spikes",
                description="Per-electrode threshold-crossing spike times",
                unit="s",
            ),
            OutputField(
                "spike_detect.rates",
                description="Per-electrode firing-rate rows for a heatmap/table panel",
                unit="Hz",
            ),
            OutputField(
                "spike_detect.summary",
                description="Detector settings and aggregate recovery counts",
            ),
        ),
        panel=PanelSpec(
            id="spike_detect_rates",
            title="Spike Detect Firing Rates",
            kind="heatmap_table",
            field="spike_detect.rates",
        ),
    )

    def compute(self, dataset: Dataset, params: SpikeDetectParams) -> dict[str, Any]:
        sampling_rate_hz = _positive_float(
            _mea_value(dataset, "sampling_rate_hz"),
            "mea.sampling_rate_hz",
        )
        traces = _trace_matrix(_mea_value(dataset, "traces"))
        channels = list(dataset.meta.channels)
        if len(traces) != len(channels):
            raise ValueError("mea.traces row count must match meta.channels")
        if not traces or not traces[0]:
            raise ValueError("mea.traces must contain at least one sample per electrode")

        duration_sec = _duration_sec(dataset, traces[0], sampling_rate_hz)
        refractory_samples = max(1, int(round((params.refractory_ms / 1000.0) * sampling_rate_hz)))
        threshold_k = _positive_float(params.threshold_k, "threshold_k")
        polarity = _polarity(params.polarity)
        low_hz, high_hz = _bandpass_edges(params, sampling_rate_hz)

        spike_rows: list[dict[str, Any]] = []
        rate_rows: list[dict[str, Any]] = []
        total_spikes = 0
        for electrode, trace in zip(channels, traces, strict=True):
            filtered = _bandpass(trace, sampling_rate_hz, low_hz, high_hz)
            noise_rms = _trimmed_rms(filtered)
            threshold = threshold_k * noise_rms
            spike_indices = _threshold_crossings(
                filtered,
                threshold=threshold,
                refractory_samples=refractory_samples,
                polarity=polarity,
            )
            spike_times = [round(index / sampling_rate_hz, 6) for index in spike_indices]
            rate_hz = len(spike_times) / duration_sec
            total_spikes += len(spike_times)
            spike_rows.append(
                {
                    "electrode": electrode,
                    "spike_times_sec": spike_times,
                    "spike_count": len(spike_times),
                    "rate_hz": rate_hz,
                    "noise_rms": noise_rms,
                    "threshold": threshold,
                }
            )
            rate_rows.append(
                {
                    "electrode": electrode,
                    "rate_hz": rate_hz,
                    "spike_count": len(spike_times),
                }
            )

        return {
            "spike_detect": {
                "spikes": spike_rows,
                "rates": rate_rows,
                "summary": {
                    "method_note": "reference template; not a full spike sorter",
                    "total_spikes": total_spikes,
                    "duration_sec": duration_sec,
                    "threshold_k": threshold_k,
                    "bandpass_hz": {"low": low_hz, "high": high_hz},
                    "refractory_ms": params.refractory_ms,
                    "polarity": polarity,
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


def _trace_matrix(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        raise ValueError("mea.traces must be a channel-major matrix")
    matrix: list[list[float]] = []
    expected_width = None
    for row in value:
        if not isinstance(row, list) or not row:
            raise ValueError("each mea.traces row must be a non-empty list")
        trace = [float(sample) for sample in row]
        if expected_width is None:
            expected_width = len(trace)
        elif len(trace) != expected_width:
            raise ValueError("all mea.traces rows must have the same sample count")
        matrix.append(trace)
    return matrix


def _duration_sec(dataset: Any, trace: list[float], sampling_rate_hz: float) -> float:
    try:
        return _positive_float(_mea_value(dataset, "duration_sec"), "mea.duration_sec")
    except ValueError:
        return len(trace) / sampling_rate_hz


def _polarity(value: str) -> str:
    if value not in {"negative", "positive", "both"}:
        raise ValueError("polarity must be one of: negative, positive, both")
    return value


def _bandpass_edges(params: SpikeDetectParams, sampling_rate_hz: float) -> tuple[float, float]:
    nyquist = sampling_rate_hz / 2.0
    low_hz = max(0.0, float(params.bandpass_low_hz))
    high_hz = min(float(params.bandpass_high_hz), nyquist * 0.99)
    if not math.isfinite(low_hz) or not math.isfinite(high_hz) or high_hz <= 0:
        raise ValueError("bandpass edges must be finite positive frequencies")
    if low_hz >= high_hz:
        raise ValueError("bandpass_low_hz must be less than bandpass_high_hz")
    return low_hz, high_hz


def _bandpass(trace: list[float], sampling_rate_hz: float, low_hz: float, high_hz: float) -> list[float]:
    return _low_pass(_high_pass(trace, sampling_rate_hz, low_hz), sampling_rate_hz, high_hz)


def _high_pass(trace: list[float], sampling_rate_hz: float, cutoff_hz: float) -> list[float]:
    if cutoff_hz <= 0:
        return list(trace)
    dt = 1.0 / sampling_rate_hz
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    alpha = rc / (rc + dt)
    output = [0.0] * len(trace)
    previous_input = trace[0]
    for index in range(1, len(trace)):
        output[index] = alpha * (output[index - 1] + trace[index] - previous_input)
        previous_input = trace[index]
    return output


def _low_pass(trace: list[float], sampling_rate_hz: float, cutoff_hz: float) -> list[float]:
    dt = 1.0 / sampling_rate_hz
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    alpha = dt / (rc + dt)
    output = [trace[0]]
    for sample in trace[1:]:
        output.append(output[-1] + alpha * (sample - output[-1]))
    return output


def _trimmed_rms(trace: list[float]) -> float:
    if not trace:
        return 0.0
    absolute = sorted(abs(sample) for sample in trace)
    keep = max(1, int(len(absolute) * 0.95))
    trimmed = absolute[:keep]
    return math.sqrt(sum(sample * sample for sample in trimmed) / len(trimmed))


def _threshold_crossings(
    trace: list[float],
    *,
    threshold: float,
    refractory_samples: int,
    polarity: str,
) -> list[int]:
    if threshold <= 0:
        return []
    indices: list[int] = []
    index = 0
    last_index = -refractory_samples
    while index < len(trace):
        if not _crosses(trace[index], threshold, polarity):
            index += 1
            continue
        start = index
        while index < len(trace) and _crosses(trace[index], threshold, polarity):
            index += 1
        stop = index
        selected = _select_extreme(trace, start, stop, polarity)
        if selected - last_index >= refractory_samples:
            indices.append(selected)
            last_index = selected
    return indices


def _crosses(sample: float, threshold: float, polarity: str) -> bool:
    if polarity == "negative":
        return sample <= -threshold
    if polarity == "positive":
        return sample >= threshold
    return abs(sample) >= threshold


def _select_extreme(trace: list[float], start: int, stop: int, polarity: str) -> int:
    if polarity == "negative":
        return min(range(start, stop), key=lambda index: trace[index])
    if polarity == "positive":
        return max(range(start, stop), key=lambda index: trace[index])
    return max(range(start, stop), key=lambda index: abs(trace[index]))


method = SpikeDetect()


__all__ = ["SpikeDetect", "SpikeDetectParams", "method", "register"]
