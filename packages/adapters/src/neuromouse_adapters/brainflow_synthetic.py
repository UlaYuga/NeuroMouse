from __future__ import annotations

import math
from collections.abc import Sequence

from neuromouse_adapters.file_replay import _dataset_from_signals


def read_brainflow_synthetic(
    *,
    channel_names: Sequence[str] | None = None,
    n_channels: int | None = None,
    n_samples: int = 256,
    sampling_rate_hz: float = 250.0,
) -> dict:
    """Emit a BrainFlow synthetic-board compatible dataset without hardware."""
    channels = _resolve_channels(channel_names=channel_names, n_channels=n_channels)
    sample_count = _positive_int(n_samples, "n_samples")
    sample_rate = _positive_float(sampling_rate_hz, "sampling_rate_hz")
    samples_by_channel = _synthetic_samples(
        channel_count=len(channels),
        n_samples=sample_count,
        sampling_rate_hz=sample_rate,
    )

    dataset = _dataset_from_signals(
        channels=channels,
        samples_by_channel=samples_by_channel,
        sampling_rate_hz=sample_rate,
        source="brainflow://synthetic-board/self-contained",
    )
    dataset["meta"]["analysis_by"] = "neuromouse_adapters.brainflow_synthetic"
    dataset["meta"]["brainflow_board"] = "SYNTHETIC_BOARD"
    return dataset


def _resolve_channels(
    *,
    channel_names: Sequence[str] | None,
    n_channels: int | None,
) -> list[str]:
    if channel_names is not None:
        channels = [_clean_channel_name(name, index) for index, name in enumerate(channel_names)]
        if n_channels is not None and n_channels != len(channels):
            raise ValueError("n_channels must match channel_names length")
        if not channels:
            raise ValueError("channel_names must contain at least one channel")
        return channels

    count = _positive_int(32 if n_channels is None else n_channels, "n_channels")
    return [f"Synthetic-{index + 1:04d}" for index in range(count)]


def _synthetic_samples(
    *,
    channel_count: int,
    n_samples: int,
    sampling_rate_hz: float,
) -> list[list[float]]:
    samples_by_channel: list[list[float]] = []
    for channel_index in range(channel_count):
        alpha_hz = 8.0 + (channel_index % 21) * 0.25
        slow_hz = 1.0 + (channel_index % 5) * 0.5
        phase = channel_index * 0.173
        amplitude = 1.0 + (channel_index % 11) * 0.03
        channel_samples = [
            amplitude
            * math.sin((2.0 * math.pi * alpha_hz * sample_index / sampling_rate_hz) + phase)
            + 0.1
            * math.sin(
                (2.0 * math.pi * slow_hz * sample_index / sampling_rate_hz) + (phase / 2.0)
            )
            for sample_index in range(n_samples)
        ]
        samples_by_channel.append(channel_samples)
    return samples_by_channel


def _clean_channel_name(name: object, index: int) -> str:
    clean = str(name).strip()
    return clean or f"Synthetic-{index + 1:04d}"


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or int(value) != value or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _positive_float(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number
