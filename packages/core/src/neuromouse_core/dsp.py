from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy import fft
from scipy.signal import windows


@dataclass(frozen=True)
class ChannelDspResult:
    frequencies: np.ndarray
    psd: np.ndarray
    metrics: dict[str, float]


def compute_channel(
    signal: Iterable[float] | np.ndarray,
    *,
    sampling_rate: float,
    window_sec: float = 4.0,
    overlap: float = 0.5,
    min_hz: float = 1.0,
    max_hz: float = 55.0,
) -> ChannelDspResult:
    freqs, psd = welch_psd(
        signal,
        sampling_rate=sampling_rate,
        window_sec=window_sec,
        overlap=overlap,
    )
    trimmed_freqs, trimmed_psd = trim_frequency_band(freqs, psd, min_hz=min_hz, max_hz=max_hz)
    return ChannelDspResult(
        frequencies=trimmed_freqs,
        psd=trimmed_psd,
        metrics=spectral_metrics(trimmed_psd, trimmed_freqs),
    )


def compute_channels(
    buffers: Iterable[Iterable[float] | np.ndarray],
    *,
    sampling_rate: float,
    window_sec: float = 4.0,
    overlap: float = 0.5,
    min_hz: float = 1.0,
    max_hz: float = 55.0,
) -> list[ChannelDspResult]:
    return [
        compute_channel(
            buffer,
            sampling_rate=sampling_rate,
            window_sec=window_sec,
            overlap=overlap,
            min_hz=min_hz,
            max_hz=max_hz,
        )
        for buffer in buffers
    ]


def welch_psd(
    signal: Iterable[float] | np.ndarray,
    *,
    sampling_rate: float,
    window_sec: float = 4.0,
    overlap: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    sampling_rate = float(sampling_rate)
    if not math.isfinite(sampling_rate) or sampling_rate <= 0:
        raise ValueError("DSP worker requires a positive sampling_rate")

    samples = np.asarray(signal, dtype=np.float32)
    if samples.ndim != 1:
        raise ValueError("Welch PSD expects a one-dimensional signal")

    win_len = min(len(samples), next_pow2(_js_round(float(window_sec) * sampling_rate)))
    if win_len < 8:
        raise ValueError("DSP worker needs at least 8 samples for Welch PSD")

    step = max(1, _js_round(win_len * (1 - float(overlap))))
    hann = windows.hann(win_len, sym=True).astype(np.float64, copy=False)
    hann_power = float(np.sum(hann * hann))
    psd = np.zeros((win_len // 2) + 1, dtype=np.float64)
    count = 0

    for start in range(0, len(samples) - win_len + 1, step):
        segment = samples[start : start + win_len].astype(np.float64, copy=False)
        transformed = fft.rfft(segment * hann)
        power = (transformed.real * transformed.real + transformed.imag * transformed.imag) / (
            sampling_rate * hann_power
        )
        if len(power) > 2:
            power[1:-1] *= 2
        psd += power
        count += 1

    psd /= max(1, count)
    freqs = np.array(
        [(index * sampling_rate) / win_len for index in range((win_len // 2) + 1)],
        dtype=np.float64,
    )
    return freqs, psd


def trim_frequency_band(
    freqs: Iterable[float] | np.ndarray,
    psd: Iterable[float] | np.ndarray,
    *,
    min_hz: float,
    max_hz: float,
) -> tuple[np.ndarray, np.ndarray]:
    freq_values = np.asarray(freqs, dtype=np.float64)
    psd_values = np.asarray(psd, dtype=np.float64)
    if freq_values.shape != psd_values.shape:
        raise ValueError("frequencies and PSD must have matching shapes")

    mask = (freq_values >= min_hz) & (freq_values <= max_hz)
    return freq_values[mask].copy(), psd_values[mask].copy()


def spectral_metrics(
    psd: Iterable[float] | np.ndarray,
    freqs: Iterable[float] | np.ndarray,
) -> dict[str, float]:
    psd_values = np.asarray(psd, dtype=np.float64)
    freq_values = np.asarray(freqs, dtype=np.float64)
    if psd_values.shape != freq_values.shape:
        raise ValueError("PSD and frequencies must have matching shapes")
    if psd_values.size == 0:
        raise ValueError("spectral metrics require at least one frequency bin")

    finite_psd = np.where(np.isnan(psd_values), 0.0, psd_values)
    values = np.maximum(finite_psd, 1e-18)
    sum_power = float(np.sum(values)) or 1e-18
    probabilities = values / sum_power

    centroid = float(np.sum(freq_values * probabilities))
    spread = float(np.sqrt(np.sum(((freq_values - centroid) ** 2) * probabilities)))
    entropy_bits = float(
        -np.sum(np.where(probabilities > 0, probabilities * np.log2(probabilities), 0.0))
    )
    entropy_normalized = entropy_bits / max(1e-18, math.log2(len(probabilities) or 2))
    geometric_mean = float(np.exp(np.sum(np.log(values)) / len(values)))
    arithmetic_mean = sum_power / len(values)
    flatness = geometric_mean / max(1e-18, arithmetic_mean)
    edge95 = _spectral_edge(values, freq_values, sum_power, 0.95)
    alpha_power = float(np.sum(values[(freq_values >= 8) & (freq_values <= 13)]))

    return {
        "centroid": centroid,
        "spread": spread,
        "entropy": entropy_bits,
        "entropy_normalized": entropy_normalized,
        "flatness": flatness,
        "edge95": edge95,
        "alpha_relative_power": alpha_power / sum_power,
    }


def next_pow2(value: int | float) -> int:
    return 2 ** math.ceil(math.log2(max(2, value)))


def _spectral_edge(
    values: np.ndarray,
    freqs: np.ndarray,
    sum_power: float,
    fraction: float,
) -> float:
    cumulative = np.cumsum(values)
    index = int(np.searchsorted(cumulative, fraction * sum_power, side="left"))
    return float(freqs[min(index, len(freqs) - 1)])


def _js_round(value: float) -> int:
    return math.floor(value + 0.5)


__all__ = [
    "ChannelDspResult",
    "compute_channel",
    "compute_channels",
    "next_pow2",
    "spectral_metrics",
    "trim_frequency_band",
    "welch_psd",
]
