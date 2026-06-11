# Method Authoring

The SDK method surface is intentionally small: declare a name, version, typed params, the
contract fields your method consumes, the output fields/panel it produces, and a `compute()`
function.

```python
from dataclasses import dataclass
from typing import Any

from neuromouse_contract import Dataset
from neuromouse_sdk import OutputField, OutputSpec, PanelSpec


@dataclass(frozen=True)
class BandPowerParams:
    min_hz: float = 8.0
    max_hz: float = 13.0


class BandPowerSummary:
    name = "band_power_summary"
    version = "0.0.0"
    params_type = BandPowerParams
    required_inputs = ("meta.channels", "welch_psd.frequencies", "welch_psd.psd")
    output = OutputSpec(
        fields=(
            OutputField("band_power_summary.band"),
            OutputField("band_power_summary.channels"),
            OutputField("band_power_summary.mean_power"),
            OutputField("band_power_summary.top_channel"),
        ),
        panel=PanelSpec(
            id="band_power_summary",
            title="Band Power Summary",
            kind="table",
            field="band_power_summary.channels",
        ),
    )

    def compute(self, dataset: Dataset, params: BandPowerParams) -> dict[str, Any]:
        rows = []
        for channel, psd_row in zip(dataset.meta.channels, dataset.welch_psd.psd, strict=True):
            rows.append({"channel": channel, "power": sum(psd_row)})
        top_channel = max(rows, key=lambda row: row["power"])
        return {
            "band_power_summary": {
                "band": {"min_hz": params.min_hz, "max_hz": params.max_hz},
                "channels": rows,
                "mean_power": sum(row["power"] for row in rows) / len(rows),
                "top_channel": top_channel,
            }
        }
```

Use `packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py` as the full working
example. The platform registry validates every `required_inputs` path before calling
`compute()`, coerces params into `params_type`, records `name` and `version` in run provenance,
and rejects results that do not contain every declared `output.fields` path. If `output.panel`
is present, its `field` must point at one of the declared output fields so the UI can expose the
result without guessing.

For a new method, copy `packages/sdk/templates/method_template.py`, rename the class and output
root key, keep the declared field paths aligned with the returned dictionary, then register the
method with `neuromouse_core.method_registry.MethodRegistry`.
