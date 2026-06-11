from __future__ import annotations

import json
from pathlib import Path

from neuromouse_contract import validate_dataset
from neuromouse_sdk import OutputField, PanelSpec, build_params
from neuromouse_sdk.examples.band_power_summary import BandPowerParams, band_power_summary

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "datasets" / "golden" / "data.json"


def test_band_power_example_exposes_the_author_surface() -> None:
    assert band_power_summary.name == "band_power_summary"
    assert band_power_summary.version == "0.0.0"
    assert band_power_summary.params_type is BandPowerParams
    assert band_power_summary.required_inputs == (
        "meta.channels",
        "welch_psd.frequencies",
        "welch_psd.psd",
    )
    assert band_power_summary.output.fields == (
        OutputField("band_power_summary.band", description="Frequency band used for integration"),
        OutputField("band_power_summary.channels", description="Per-channel band-power rows"),
        OutputField("band_power_summary.mean_power", description="Mean band power across channels"),
        OutputField(
            "band_power_summary.top_channel",
            description="Channel with highest band power",
        ),
    )
    assert band_power_summary.output.panel == PanelSpec(
        id="band_power_summary",
        title="Band Power Summary",
        kind="table",
        field="band_power_summary.channels",
    )


def test_build_params_coerces_author_dataclasses_from_dicts() -> None:
    params = build_params(BandPowerParams, {"min_hz": 4.0, "max_hz": 8.0})

    assert params == BandPowerParams(min_hz=4.0, max_hz=8.0)


def test_band_power_example_computes_declared_payload_shape() -> None:
    dataset = validate_dataset(json.loads(GOLDEN_PATH.read_text(encoding="utf-8")))

    result = band_power_summary.compute(dataset, BandPowerParams(min_hz=8.0, max_hz=13.0))

    assert set(result) == {"band_power_summary"}
    summary = result["band_power_summary"]
    assert summary["band"] == {"min_hz": 8.0, "max_hz": 13.0}
    assert len(summary["channels"]) == len(dataset.meta.channels)
    assert summary["top_channel"]["channel"] in dataset.meta.channels
    assert summary["top_channel"]["power"] == max(row["power"] for row in summary["channels"])
    assert summary["mean_power"] > 0.0
