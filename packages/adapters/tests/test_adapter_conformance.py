from __future__ import annotations

import csv
import math
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from neuromouse_adapters import read_file
from neuromouse_adapters.brainflow_synthetic import read_brainflow_synthetic
from neuromouse_adapters.conformance import assert_adapter_conforms

HIGH_CHANNEL_COUNT = 1025


def _write_csv(path: Path, channel_names: list[str], n_samples: int) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_sec", *channel_names])
        for sample_index in range(n_samples):
            time_sec = sample_index / 250.0
            writer.writerow(
                [
                    f"{time_sec:.6f}",
                    *[
                        f"{math.sin((sample_index + 1) * (channel_index + 1) / 17.0):.8f}"
                        for channel_index in range(len(channel_names))
                    ],
                ]
            )


def _channel_names(prefix: str, count: int) -> list[str]:
    return [f"{prefix}-{index:04d}" for index in range(count)]


@pytest.mark.parametrize(
    ("adapter_name", "factory", "expected_channels"),
    [
        (
            "read_file_csv",
            lambda: _read_file_csv_case(
                channel_names=["Grid A1", "Grid-B2", "well_003"],
                n_samples=17,
            ),
            ["Grid A1", "Grid-B2", "well_003"],
        ),
        (
            "brainflow_synthetic",
            lambda: read_brainflow_synthetic(
                channel_names=["SYN-A", "SYN-B", "SYN-C", "SYN-D"],
                n_samples=33,
                sampling_rate_hz=512.0,
            ),
            ["SYN-A", "SYN-B", "SYN-C", "SYN-D"],
        ),
    ],
)
def test_adapters_pass_shared_conformance_suite(
    adapter_name: str,
    factory: Callable[[], dict],
    expected_channels: list[str],
) -> None:
    dataset = factory()

    assert dataset["meta"]["channels"] == expected_channels
    assert_adapter_conforms(dataset, adapter_name=adapter_name)


@pytest.mark.parametrize(
    ("channel_count", "n_samples", "sampling_rate_hz"),
    [
        (1, 8, 128.0),
        (32, 31, 250.0),
        (129, 16, 500.0),
        (512, 9, 1_000.0),
        (1024, 8, 2_000.0),
        (HIGH_CHANNEL_COUNT, 8, 2_000.0),
    ],
)
def test_brainflow_synthetic_conforms_for_montage_sizes_sample_rates_and_lengths(
    channel_count: int,
    n_samples: int,
    sampling_rate_hz: float,
) -> None:
    channel_names = _channel_names("MEA", channel_count)

    dataset = read_brainflow_synthetic(
        channel_names=channel_names,
        n_samples=n_samples,
        sampling_rate_hz=sampling_rate_hz,
    )

    assert dataset["meta"]["channels"] == channel_names
    assert dataset["meta"]["n_channels"] == channel_count
    assert dataset["meta"]["sampling_rate_analysis_hz"] == sampling_rate_hz
    assert_adapter_conforms(dataset, adapter_name="brainflow_synthetic")


def test_read_file_conforms_at_hd_mea_scale(tmp_path: Path) -> None:
    channel_names = _channel_names("HDMEA", HIGH_CHANNEL_COUNT)
    csv_path = tmp_path / "hd_mea.csv"
    _write_csv(csv_path, channel_names=channel_names, n_samples=8)

    dataset = read_file(csv_path)

    assert dataset["meta"]["channels"] == channel_names
    assert_adapter_conforms(dataset, adapter_name="read_file_csv")


@st.composite
def _adapter_dimensions(draw: st.DrawFn) -> tuple[int, int, float, str]:
    channel_count = draw(
        st.one_of(
            st.integers(min_value=1, max_value=128),
            st.sampled_from([256, 512, 1024, HIGH_CHANNEL_COUNT]),
        )
    )
    n_samples = draw(st.integers(min_value=8, max_value=40))
    sampling_rate_hz = draw(st.sampled_from([64.0, 128.0, 250.0, 512.0, 1_000.0]))
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
    return channel_count, n_samples, sampling_rate_hz, prefix


@settings(max_examples=25, deadline=None)
@given(_adapter_dimensions())
def test_brainflow_synthetic_conforms_for_hypothesis_dimensions(
    dimensions: tuple[int, int, float, str]
) -> None:
    channel_count, n_samples, sampling_rate_hz, prefix = dimensions
    channel_names = _channel_names(prefix, channel_count)

    dataset = read_brainflow_synthetic(
        channel_names=channel_names,
        n_samples=n_samples,
        sampling_rate_hz=sampling_rate_hz,
    )

    assert_adapter_conforms(dataset, adapter_name="brainflow_synthetic")


def test_conformance_helper_rejects_non_finite_adapter_values() -> None:
    dataset = read_brainflow_synthetic(
        channel_names=["finite-0", "finite-1"],
        n_samples=16,
        sampling_rate_hz=250.0,
    )
    dataset["welch_psd"]["psd"][0][0] = math.inf

    with pytest.raises(AssertionError, match="finite"):
        assert_adapter_conforms(dataset, adapter_name="broken_adapter")


def _read_file_csv_case(channel_names: list[str], n_samples: int) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        csv_path = Path(directory) / "case.csv"
        _write_csv(csv_path, channel_names=channel_names, n_samples=n_samples)
        return read_file(csv_path)
