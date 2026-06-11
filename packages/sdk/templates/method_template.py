from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neuromouse_contract import Dataset
from neuromouse_sdk import OutputField, OutputSpec, PanelSpec


@dataclass(frozen=True)
class MyMethodParams:
    threshold: float = 0.5


class MyMethod:
    name = "my_method"
    params_type = MyMethodParams
    required_inputs = ("meta.channels", "welch_psd.frequencies", "welch_psd.psd")
    output = OutputSpec(
        fields=(
            OutputField("my_method.rows", description="Rows to expose in the panel"),
            OutputField("my_method.summary", description="Small scalar summary"),
        ),
        panel=PanelSpec(
            id="my_method",
            title="My Method",
            kind="table",
            field="my_method.rows",
        ),
    )

    def compute(self, dataset: Dataset, params: MyMethodParams) -> dict[str, Any]:
        rows = [
            {"channel": channel, "above_threshold": index >= params.threshold}
            for index, channel in enumerate(dataset.meta.channels)
        ]
        return {
            "my_method": {
                "rows": rows,
                "summary": {"channels": len(rows), "threshold": params.threshold},
            }
        }


method = MyMethod()
