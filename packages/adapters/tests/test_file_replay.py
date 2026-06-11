from __future__ import annotations

import csv
import math
import struct
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from neuromouse_adapters import read_file
from neuromouse_adapters.conformance import assert_adapter_conforms

HIGH_CHANNEL_COUNT = 1025


def _edf_field(value: object, width: int) -> bytes:
    text = str(value)
    if len(text) > width:
        text = text[:width]
    return text.ljust(width).encode("ascii")


def _write_tiny_edf(path: Path) -> None:
    channel_names = ["Fp1", "Cz"]
    samples_by_channel = [
        [0, 1, 0, -1, 0, 1, 0, -1],
        [1, 1, -1, -1, 1, 1, -1, -1],
    ]
    n_channels = len(channel_names)
    header_bytes = 256 + (256 * n_channels)

    fixed = b"".join(
        [
            _edf_field(0, 8),
            _edf_field("test patient", 80),
            _edf_field("test recording", 80),
            _edf_field("11.06.26", 8),
            _edf_field("12.00.00", 8),
            _edf_field(header_bytes, 8),
            _edf_field("", 44),
            _edf_field(1, 8),
            _edf_field(1, 8),
            _edf_field(n_channels, 4),
        ]
    )
    signal_header = b"".join(_edf_field(name, 16) for name in channel_names)
    signal_header += b"".join(_edf_field("", 80) for _ in channel_names)
    signal_header += b"".join(_edf_field("uV", 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(-100, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(100, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(-32768, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(32767, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field("", 80) for _ in channel_names)
    signal_header += b"".join(_edf_field(len(samples_by_channel[0]), 8) for _ in channel_names)
    signal_header += b"".join(_edf_field("", 32) for _ in channel_names)

    data = b"".join(
        struct.pack("<h", int(round(sample * 327.67)))
        for channel_samples in samples_by_channel
        for sample in channel_samples
    )
    path.write_bytes(fixed + signal_header + data)


def _pack_int24_le(value: int) -> bytes:
    if value < 0:
        value += 1 << 24
    return bytes((value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF))


def _write_tiny_bdf(path: Path) -> None:
    channel_names = ["A1", "A2", "Ref"]
    samples_by_channel = [
        [0, 100_000, 0, -100_000, 0, 100_000],
        [50_000, 50_000, -50_000, -50_000, 50_000, 50_000],
        [25_000, -25_000, 25_000, -25_000, 25_000, -25_000],
    ]
    n_channels = len(channel_names)
    header_bytes = 256 + (256 * n_channels)

    fixed = b"".join(
        [
            _edf_field(0, 8),
            _edf_field("test patient", 80),
            _edf_field("test recording", 80),
            _edf_field("11.06.26", 8),
            _edf_field("12.00.00", 8),
            _edf_field(header_bytes, 8),
            _edf_field("", 44),
            _edf_field(1, 8),
            _edf_field(1, 8),
            _edf_field(n_channels, 4),
        ]
    )
    signal_header = b"".join(_edf_field(name, 16) for name in channel_names)
    signal_header += b"".join(_edf_field("", 80) for _ in channel_names)
    signal_header += b"".join(_edf_field("uV", 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(-100, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(100, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(-8_388_608, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field(8_388_607, 8) for _ in channel_names)
    signal_header += b"".join(_edf_field("", 80) for _ in channel_names)
    signal_header += b"".join(_edf_field(len(samples_by_channel[0]), 8) for _ in channel_names)
    signal_header += b"".join(_edf_field("", 32) for _ in channel_names)

    data = b"".join(
        _pack_int24_le(sample)
        for channel_samples in samples_by_channel
        for sample in channel_samples
    )
    path.write_bytes(fixed + signal_header + data)


def _write_csv(path: Path, channel_names: list[str], n_samples: int = 16) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_sec", *channel_names])
        for i in range(n_samples):
            time_sec = i / 8
            writer.writerow(
                [
                    f"{time_sec:.6f}",
                    *[
                        f"{math.sin((i + 1) * (channel_index + 1)):.8f}"
                        for channel_index in range(len(channel_names))
                    ],
                ]
            )


def test_read_file_round_trips_tiny_edf(tmp_path: Path) -> None:
    edf_path = tmp_path / "tiny.edf"
    _write_tiny_edf(edf_path)

    dataset = read_file(edf_path)

    assert dataset["meta"]["channels"] == ["Fp1", "Cz"]
    assert dataset["meta"]["n_channels"] == 2
    assert_adapter_conforms(dataset, adapter_name="read_file_edf")


def test_read_file_round_trips_tiny_bdf(tmp_path: Path) -> None:
    bdf_path = tmp_path / "tiny.bdf"
    _write_tiny_bdf(bdf_path)

    dataset = read_file(bdf_path)

    assert dataset["meta"]["channels"] == ["A1", "A2", "Ref"]
    assert dataset["meta"]["n_channels"] == 3
    assert_adapter_conforms(dataset, adapter_name="read_file_bdf")


def test_read_file_round_trips_channel_per_column_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "tiny.csv"
    _write_csv(csv_path, ["Fp1", "Cz", "Oz"])

    dataset = read_file(csv_path)

    assert dataset["meta"]["channels"] == ["Fp1", "Cz", "Oz"]
    assert dataset["meta"]["n_channels"] == 3
    assert_adapter_conforms(dataset, adapter_name="read_file_csv")


def test_read_file_rejects_empty_csv_channel_set(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("time_sec\n0.0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one channel"):
        read_file(csv_path)


@st.composite
def _csv_cases(draw: st.DrawFn) -> tuple[list[str], int]:
    n_channels = draw(
        st.one_of(
            st.integers(min_value=1, max_value=128),
            st.sampled_from([256, 512, 1024, HIGH_CHANNEL_COUNT]),
        )
    )
    max_samples = 16 if n_channels >= 512 else 48
    n_samples = draw(st.integers(min_value=8, max_value=max_samples))
    prefix = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Ll", "Lu", "Nd"),
                whitelist_characters=("_", "-"),
            ),
            min_size=1,
            max_size=8,
        )
    )
    names = [f"{prefix}_{index}" for index in range(n_channels)]
    return names, n_samples


@settings(max_examples=30, deadline=None)
@given(_csv_cases())
def test_csv_replay_conforms_for_random_channel_counts_names_and_lengths(
    case: tuple[list[str], int]
) -> None:
    channel_names, n_samples = case
    with tempfile.TemporaryDirectory() as directory:
        csv_path = Path(directory) / "random.csv"
        _write_csv(csv_path, channel_names, n_samples=n_samples)

        dataset = read_file(csv_path)

    assert dataset["meta"]["channels"] == channel_names
    assert_adapter_conforms(dataset, adapter_name="read_file_csv")
