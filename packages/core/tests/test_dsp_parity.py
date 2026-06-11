from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from neuromouse_core.dsp import compute_channel, spectral_metrics, welch_psd

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "datasets" / "golden" / "data.json"

SYNTHETIC_PSD_ATOL = 1e-13
SYNTHETIC_METRIC_ATOL = {
    "alpha_relative_power": 2e-15,
    "centroid": 1e-13,
    "edge95": 0.0,
    "entropy": 5e-15,
    "entropy_normalized": 1e-15,
    "flatness": 1e-16,
    "spread": 5e-14,
}
GOLDEN_METRIC_ATOL = 0.0


def _js_round(value: float) -> int:
    return math.floor(value + 0.5)


def _next_pow2(value: int) -> int:
    return 2 ** math.ceil(math.log2(max(2, value)))


def _fft_like_js(re: np.ndarray, im: np.ndarray) -> None:
    n = len(re)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]

    length = 2
    while length <= n:
        angle = (-2 * math.pi) / length
        w_re = math.cos(angle)
        w_im = math.sin(angle)
        for i in range(0, n, length):
            u_re = 1.0
            u_im = 0.0
            for j in range(length // 2):
                even = i + j
                odd = even + length // 2
                v_re = re[odd] * u_re - im[odd] * u_im
                v_im = re[odd] * u_im + im[odd] * u_re
                re[odd] = re[even] - v_re
                im[odd] = im[even] - v_im
                re[even] += v_re
                im[even] += v_im
                u_re, u_im = (u_re * w_re - u_im * w_im, u_re * w_im + u_im * w_re)
        length <<= 1


def _reference_welch_psd(
    signal: np.ndarray,
    sampling_rate: float,
    window_sec: float = 4.0,
    overlap: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    signal = np.asarray(signal, dtype=np.float32)
    win_len = min(len(signal), _next_pow2(_js_round(window_sec * sampling_rate)))
    if win_len < 8:
        raise ValueError("DSP worker needs at least 8 samples for Welch PSD")

    step = max(1, _js_round(win_len * (1 - overlap)))
    hann = np.array(
        [0.5 * (1 - math.cos((2 * math.pi * index) / (win_len - 1))) for index in range(win_len)],
        dtype=np.float64,
    )
    hann_power = float(np.sum(hann * hann))
    psd = np.zeros(win_len // 2 + 1, dtype=np.float64)
    count = 0

    for start in range(0, len(signal) - win_len + 1, step):
        re = np.zeros(win_len, dtype=np.float64)
        im = np.zeros(win_len, dtype=np.float64)
        re[:] = signal[start : start + win_len].astype(np.float64) * hann
        _fft_like_js(re, im)
        for index in range((win_len // 2) + 1):
            value = ((re[index] * re[index]) + (im[index] * im[index])) / (
                sampling_rate * hann_power
            )
            if 0 < index < win_len / 2:
                value *= 2
            psd[index] += value
        count += 1

    psd /= max(1, count)
    freqs = np.array(
        [(index * sampling_rate) / win_len for index in range((win_len // 2) + 1)],
        dtype=np.float64,
    )
    return freqs, psd


def _reference_trim(
    freqs: np.ndarray,
    psd: np.ndarray,
    min_hz: float = 1.0,
    max_hz: float = 55.0,
) -> tuple[np.ndarray, np.ndarray]:
    mask = (freqs >= min_hz) & (freqs <= max_hz)
    return freqs[mask], psd[mask]


def _reference_metrics(psd: np.ndarray, freqs: np.ndarray) -> dict[str, float]:
    values = np.maximum(np.nan_to_num(np.asarray(psd, dtype=np.float64), nan=0.0), 1e-18)
    freqs = np.asarray(freqs, dtype=np.float64)
    sum_power = float(np.sum(values)) or 1e-18
    probabilities = values / sum_power
    centroid = float(np.sum(freqs * probabilities))
    spread = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * probabilities)))
    entropy_bits = float(
        -np.sum(np.where(probabilities > 0, probabilities * np.log2(probabilities), 0))
    )
    entropy_normalized = entropy_bits / max(1e-18, math.log2(len(probabilities) or 2))
    geometric_mean = float(np.exp(np.sum(np.log(values)) / len(values)))
    arithmetic_mean = sum_power / len(values)
    flatness = geometric_mean / max(1e-18, arithmetic_mean)
    cumulative = np.cumsum(values)
    edge_index = int(np.searchsorted(cumulative, 0.95 * sum_power, side="left"))
    edge95 = float(freqs[min(edge_index, len(freqs) - 1)])
    alpha_power = float(np.sum(values[(freqs >= 8) & (freqs <= 13)]))
    return {
        "centroid": centroid,
        "spread": spread,
        "entropy": entropy_bits,
        "entropy_normalized": entropy_normalized,
        "flatness": flatness,
        "edge95": edge95,
        "alpha_relative_power": alpha_power / sum_power,
    }


def _seeded_signal(seed: int, sampling_rate: float, length: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    time = np.arange(length, dtype=np.float64) / sampling_rate
    base_freqs = rng.uniform(2.0, min(45.0, sampling_rate / 2 - 2.0), size=3)
    amplitudes = rng.uniform(0.2, 2.0, size=3)
    phases = rng.uniform(-math.pi, math.pi, size=3)
    signal = np.zeros(length, dtype=np.float64)
    for frequency, amplitude, phase in zip(base_freqs, amplitudes, phases, strict=True):
        signal += amplitude * np.sin((2 * math.pi * frequency * time) + phase)
    signal += 0.05 * rng.normal(size=length)
    signal += rng.uniform(-0.02, 0.02) * np.linspace(-1.0, 1.0, length)
    return signal


def test_seeded_raw_signal_matches_js_reference_pipeline() -> None:
    signal = _seeded_signal(seed=20260611, sampling_rate=250.0, length=4096)

    result = compute_channel(signal, sampling_rate=250.0, window_sec=2.0, overlap=0.5)
    expected_freqs, expected_psd = _reference_trim(
        *_reference_welch_psd(signal, sampling_rate=250.0, window_sec=2.0, overlap=0.5)
    )
    expected_metrics = _reference_metrics(expected_psd, expected_freqs)

    np.testing.assert_allclose(result.frequencies, expected_freqs, rtol=0, atol=0)
    np.testing.assert_allclose(result.psd, expected_psd, rtol=0, atol=SYNTHETIC_PSD_ATOL)
    for key, expected in expected_metrics.items():
        assert result.metrics[key] == pytest.approx(
            expected,
            abs=SYNTHETIC_METRIC_ATOL[key],
            rel=0,
        )


def test_golden_welch_psd_static_metrics_match_js_reference() -> None:
    with GOLDEN_PATH.open("r", encoding="utf-8") as handle:
        golden = json.load(handle)

    freqs = np.asarray(golden["welch_psd"]["frequencies"], dtype=np.float64)
    psd_rows = np.asarray(golden["welch_psd"]["psd"], dtype=np.float64)

    assert freqs.shape == (217,)
    assert psd_rows.shape == (32, 217)
    for row in psd_rows:
        actual = spectral_metrics(row, freqs)
        expected = _reference_metrics(row, freqs)
        for key, expected_value in expected.items():
            assert actual[key] == pytest.approx(expected_value, abs=GOLDEN_METRIC_ATOL, rel=0)


@given(
    seed=st.integers(min_value=0, max_value=2**32 - 1),
    sampling_rate=st.sampled_from([128.0, 250.0, 500.0]),
    window_sec=st.sampled_from([1.0, 2.0, 4.0]),
    overlap=st.sampled_from([0.0, 0.25, 0.5, 0.75]),
)
@settings(
    max_examples=80,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_seeded_signal_spectral_invariants(
    seed: int,
    sampling_rate: float,
    window_sec: float,
    overlap: float,
) -> None:
    win_len = _next_pow2(_js_round(window_sec * sampling_rate))
    signal = _seeded_signal(seed, sampling_rate=sampling_rate, length=win_len * 3)

    result = compute_channel(
        signal,
        sampling_rate=sampling_rate,
        window_sec=window_sec,
        overlap=overlap,
    )
    assert result.frequencies[0] >= 1.0
    assert result.frequencies[-1] <= 55.0
    assert result.psd.shape == result.frequencies.shape
    assert np.all(np.isfinite(result.psd))
    assert np.all(result.psd >= 0.0)

    metrics = result.metrics
    assert 0.0 <= metrics["entropy_normalized"] <= 1.0 + 1e-12
    assert 0.0 <= metrics["flatness"] <= 1.0 + 1e-12
    assert result.frequencies[0] <= metrics["edge95"] <= result.frequencies[-1]
    assert result.frequencies[0] <= metrics["centroid"] <= result.frequencies[-1]
    assert 0.0 <= metrics["alpha_relative_power"] <= 1.0 + 1e-12

    full_freqs, full_psd = welch_psd(
        signal,
        sampling_rate=sampling_rate,
        window_sec=window_sec,
        overlap=overlap,
    )
    frequency_step = full_freqs[1] - full_freqs[0]
    psd_energy = float(np.sum(full_psd) * frequency_step)
    signal_energy = float(np.mean(np.asarray(signal, dtype=np.float32) ** 2))
    assert 0.0 < psd_energy <= signal_energy * 2.0


def test_golden_geometry_metric_ranges_are_normalized() -> None:
    with GOLDEN_PATH.open("r", encoding="utf-8") as handle:
        golden = json.load(handle)

    geometry = golden["geometry"]
    for metric in ("entropy", "flatness", "alpha_relative_power"):
        values = np.asarray(geometry[metric], dtype=np.float64)
        assert np.nanmin(values) >= 0.0
        assert np.nanmax(values) <= 1.0

    for metric in ("centroid", "edge95"):
        values = np.asarray(geometry[metric], dtype=np.float64)
        assert np.nanmin(values) >= 1.0
        assert np.nanmax(values) <= 55.0
