from __future__ import annotations

import csv
import json
import math
import tomllib
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from neuromouse_adapters import make_synthetic_mea, read_mea
from neuromouse_adapters.conformance import assert_adapter_conforms
from neuromouse_contract import validate_dataset

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_MEA = ROOT / "datasets" / "golden" / "mea_synthetic.json"


def _write_wide_mea_csv(
    path: Path,
    *,
    channel_names: list[str],
    n_samples: int,
    sampling_rate_hz: float,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_sec", *channel_names])
        for sample_index in range(n_samples):
            time_sec = sample_index / sampling_rate_hz
            writer.writerow(
                [
                    f"{time_sec:.6f}",
                    *[
                        f"{_synthetic_voltage(sample_index, channel_index, sampling_rate_hz):.8f}"
                        for channel_index in range(len(channel_names))
                    ],
                ]
            )


def _synthetic_voltage(sample_index: int, channel_index: int, sampling_rate_hz: float) -> float:
    base = 0.02 * math.sin(
        2.0 * math.pi * (8.0 + channel_index) * sample_index / sampling_rate_hz
    )
    spike = 1.0 if channel_index == 1 and sample_index in {8, 16, 24} else 0.0
    return base + spike


def test_make_synthetic_mea_is_deterministic_contract_valid_and_keeps_spike_ground_truth() -> None:
    dataset = make_synthetic_mea(1024, duration=0.064, seed=17)
    repeat = make_synthetic_mea(1024, duration=0.064, seed=17)

    validate_dataset(dataset)
    assert_adapter_conforms(dataset, adapter_name="synthetic_mea")
    assert dataset["meta"]["n_channels"] == 1024
    assert dataset["meta"]["channels"][0] == "MEA-0000"
    assert dataset["meta"]["channels"][-1] == "MEA-1023"
    assert dataset["meta"]["modality"] == "hd_mea"
    assert dataset["meta"]["analysis_by"] == "neuromouse_adapters.mea"
    assert "mea" in dataset
    assert dataset["mea"]["sampling_rate_hz"] == dataset["meta"]["sampling_rate_analysis_hz"]
    assert len(dataset["mea"]["traces"]) == dataset["meta"]["n_channels"]
    assert dataset["spike_ground_truth"] == repeat["spike_ground_truth"]
    assert dataset["welch_psd"]["psd"][0] == repeat["welch_psd"]["psd"][0]

    events = dataset["spike_ground_truth"]["events"]
    assert events
    assert dataset["spike_ground_truth"]["n_events"] == len(events)
    assert max(event["channel_index"] for event in events) < 1024
    assert all(event["sample_index"] >= 0 for event in events)


def test_read_mea_round_trips_documented_wide_csv_layout(tmp_path: Path) -> None:
    csv_path = tmp_path / "small_mea.csv"
    channel_names = ["wellA_e0000", "wellA_e0001", "wellA_e0002", "wellA_e0003"]
    _write_wide_mea_csv(
        csv_path,
        channel_names=channel_names,
        n_samples=32,
        sampling_rate_hz=1_000.0,
    )

    dataset = read_mea(csv_path)

    validate_dataset(dataset)
    assert_adapter_conforms(dataset, adapter_name="read_mea_csv")
    assert dataset["meta"]["channels"] == channel_names
    assert dataset["meta"]["n_channels"] == len(channel_names)
    assert dataset["meta"]["modality"] == "hd_mea"
    assert dataset["meta"]["mea"]["layout"] == "csv-wide-v1"
    assert dataset["meta"]["mea"]["sample_count"] == 32


def test_read_mea_round_trips_documented_hdf5_layout_when_h5py_is_available(
    tmp_path: Path,
) -> None:
    h5py = pytest.importorskip("h5py")
    h5_path = tmp_path / "small_mea.h5"
    channels = ["E0000", "E0001", "E0002"]
    rows = [
        [
            _synthetic_voltage(sample_index, channel_index, 1_000.0)
            for channel_index in range(len(channels))
        ]
        for sample_index in range(32)
    ]
    with h5py.File(h5_path, "w") as handle:
        handle.attrs["sampling_rate_hz"] = 1_000.0
        handle.attrs["axis_order"] = "time,channel"
        handle.create_dataset("channels", data=[name.encode("utf-8") for name in channels])
        handle.create_dataset("signals", data=rows)

    dataset = read_mea(h5_path)

    validate_dataset(dataset)
    assert_adapter_conforms(dataset, adapter_name="read_mea_hdf5")
    assert dataset["meta"]["channels"] == channels
    assert dataset["meta"]["mea"]["layout"] == "hdf5-signals-v1"
    assert dataset["meta"]["mea"]["sample_count"] == 32


@st.composite
def _synthetic_mea_cases(draw: st.DrawFn) -> tuple[int, float, int, float]:
    n_channels = draw(
        st.one_of(
            st.integers(min_value=1, max_value=64),
            st.sampled_from([128, 512, 1024]),
        )
    )
    duration = draw(st.sampled_from([0.032, 0.064, 0.128]))
    seed = draw(st.integers(min_value=0, max_value=10_000))
    sampling_rate_hz = draw(st.sampled_from([250.0, 512.0, 1_000.0]))
    return n_channels, duration, seed, sampling_rate_hz


@settings(max_examples=18, deadline=None)
@given(_synthetic_mea_cases())
def test_make_synthetic_mea_conforms_for_channel_counts_and_rates(
    case: tuple[int, float, int, float],
) -> None:
    n_channels, duration, seed, sampling_rate_hz = case

    dataset = make_synthetic_mea(
        n_channels,
        duration=duration,
        seed=seed,
        sampling_rate_hz=sampling_rate_hz,
    )

    assert dataset["meta"]["n_channels"] == n_channels
    assert dataset["meta"]["sampling_rate_analysis_hz"] > 0
    assert_adapter_conforms(dataset, adapter_name="synthetic_mea")


def test_mea_optional_dependencies_are_declared() -> None:
    pyproject = tomllib.loads((ROOT / "packages" / "adapters" / "pyproject.toml").read_text())

    mea_dependencies = pyproject["project"]["optional-dependencies"]["mea"]
    assert any(dependency.startswith("h5py") for dependency in mea_dependencies)
    assert any(dependency.startswith("spikeinterface") for dependency in mea_dependencies)


def test_1024_channel_golden_mea_fixture_is_contract_valid() -> None:
    dataset = json.loads(GOLDEN_MEA.read_text(encoding="utf-8"))

    validate_dataset(dataset)
    assert_adapter_conforms(dataset, adapter_name="golden_mea")
    assert dataset["meta"]["n_channels"] == 1024
    assert dataset["meta"]["modality"] == "hd_mea"
    assert dataset["spike_ground_truth"]["n_events"] == len(
        dataset["spike_ground_truth"]["events"]
    )
    assert dataset["spike_ground_truth"]["events"]
    assert "mea" in dataset
    assert dataset["mea"]["sampling_rate_hz"] > 0.0
    assert len(dataset["mea"]["traces"]) == dataset["meta"]["n_channels"]
