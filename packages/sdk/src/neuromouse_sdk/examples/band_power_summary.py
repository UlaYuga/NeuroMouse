from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from neuromouse_sdk import OutputField, OutputSpec, PanelSpec

if TYPE_CHECKING:
    from neuromouse_contract import Dataset


@dataclass(frozen=True)
class BandPowerParams:
    min_hz: float = 8.0
    max_hz: float = 13.0


class BandPowerSummary:
    name = "band_power_summary"
    params_type = BandPowerParams
    required_inputs = ("meta.channels", "welch_psd.frequencies", "welch_psd.psd")
    output = OutputSpec(
        fields=(
            OutputField(
                "band_power_summary.band",
                description="Frequency band used for integration",
            ),
            OutputField("band_power_summary.channels", description="Per-channel band-power rows"),
            OutputField(
                "band_power_summary.mean_power",
                description="Mean band power across channels",
            ),
            OutputField(
                "band_power_summary.top_channel",
                description="Channel with highest band power",
            ),
        ),
        panel=PanelSpec(
            id="band_power_summary",
            title="Band Power Summary",
            kind="table",
            field="band_power_summary.channels",
        ),
    )

    def compute(self, dataset: Dataset, params: BandPowerParams) -> dict[str, Any]:
        if params.min_hz > params.max_hz:
            raise ValueError("min_hz must be less than or equal to max_hz")

        frequencies = dataset.welch_psd.frequencies
        selected = [
            index
            for index, frequency in enumerate(frequencies)
            if params.min_hz <= frequency <= params.max_hz
        ]
        if not selected:
            raise ValueError("frequency band does not overlap welch_psd.frequencies")

        rows = []
        for channel, psd_row in zip(dataset.meta.channels, dataset.welch_psd.psd, strict=True):
            power = _integrate_band(frequencies, psd_row, selected)
            rows.append({"channel": channel, "power": power})

        top_channel = max(rows, key=lambda row: row["power"])
        mean_power = sum(row["power"] for row in rows) / len(rows)
        return {
            "band_power_summary": {
                "band": {"min_hz": params.min_hz, "max_hz": params.max_hz},
                "channels": rows,
                "mean_power": mean_power,
                "top_channel": top_channel,
            }
        }


def _integrate_band(frequencies: list[float], psd_row: list[float], selected: list[int]) -> float:
    if len(selected) == 1:
        return float(psd_row[selected[0]])

    power = 0.0
    for left, right in zip(selected, selected[1:]):
        width = frequencies[right] - frequencies[left]
        power += ((psd_row[left] + psd_row[right]) / 2.0) * width
    return float(power)


band_power_summary = BandPowerSummary()
