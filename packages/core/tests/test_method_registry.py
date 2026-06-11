from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from neuromouse_contract import Dataset
from neuromouse_core.method_registry import (
    MethodDeclarationError,
    MethodExecutionError,
    MethodRegistry,
    has_field_path,
)
from neuromouse_sdk import OutputField, OutputSpec, PanelSpec
from neuromouse_sdk.examples.band_power_summary import band_power_summary

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = ROOT / "datasets" / "golden" / "data.json"

VALID_INPUT_PATHS = (
    "meta.channels",
    "welch_psd.frequencies",
    "welch_psd.psd",
    "geometry.time",
    "channel_summary",
)
INVALID_INPUT_PATHS = (
    "meta.missing",
    "welch_psd.not_real",
    "geometry.alpha_relative_power.not_real",
)
VALID_OUTPUT_PATHS = (
    "analysis.value",
    "analysis.rows",
    "analysis.summary.top_channel",
)
INVALID_DECLARED_PATHS = ("", "analysis..value", ".analysis.value", "analysis.value.")


@dataclass(frozen=True)
class EmptyParams:
    pass


class OptionalInputMethod:
    name = "needs_channel_summary"
    params_type = EmptyParams
    required_inputs = ("channel_summary",)
    output = OutputSpec(fields=(OutputField("analysis.ok"),), panel=None)

    def compute(self, dataset: Dataset, params: EmptyParams) -> dict[str, Any]:
        return {"analysis": {"ok": bool(dataset.channel_summary)}}


class MissingOutputMethod:
    name = "missing_output"
    params_type = EmptyParams
    required_inputs = ("meta.channels",)
    output = OutputSpec(fields=(OutputField("analysis.required"),), panel=None)

    def compute(self, dataset: Dataset, params: EmptyParams) -> dict[str, Any]:
        return {"analysis": {"wrong": len(dataset.meta.channels)}}


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_method_missing_a_declared_input_field_is_rejected() -> None:
    dataset = load_golden()
    dataset.pop("channel_summary")
    registry = MethodRegistry()
    registry.register(OptionalInputMethod())

    with pytest.raises(MethodExecutionError, match="channel_summary"):
        registry.run("needs_channel_summary", dataset)


def test_method_missing_a_declared_output_field_is_rejected() -> None:
    registry = MethodRegistry()
    registry.register(MissingOutputMethod())

    with pytest.raises(MethodExecutionError, match="analysis.required"):
        registry.run("missing_output", load_golden())


def test_example_registers_runs_on_golden_and_exposes_output_spec() -> None:
    registry = MethodRegistry()
    registry.register(band_power_summary)

    run = registry.run("band_power_summary", load_golden(), params={"min_hz": 8.0, "max_hz": 13.0})

    assert registry.lookup("band_power_summary") is band_power_summary
    assert run.method_name == "band_power_summary"
    assert run.output_spec == band_power_summary.output
    assert run.output_spec.panel == PanelSpec(
        id="band_power_summary",
        title="Band Power Summary",
        kind="table",
        field="band_power_summary.channels",
    )
    assert all(has_field_path(run.result, field.path) for field in run.output_spec.fields)
    summary = run.result["band_power_summary"]
    assert len(summary["channels"]) == load_golden()["meta"]["n_channels"]
    assert summary["mean_power"] == pytest.approx(
        sum(row["power"] for row in summary["channels"]) / len(summary["channels"])
    )


@st.composite
def method_declarations(draw: st.DrawFn) -> dict[str, Any]:
    name = draw(st.sampled_from(["generated", " generated ", "", "   "]))
    required_inputs = draw(
        st.lists(
            st.sampled_from(VALID_INPUT_PATHS + INVALID_INPUT_PATHS + INVALID_DECLARED_PATHS),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )
    output_fields = draw(
        st.lists(
            st.sampled_from(VALID_OUTPUT_PATHS + INVALID_DECLARED_PATHS),
            min_size=0,
            max_size=3,
            unique=True,
        )
    )
    return {"name": name, "required_inputs": required_inputs, "output_fields": output_fields}


def _result_for_paths(paths: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in paths:
        cursor = result
        parts = path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = "ok"
    return result


@given(declaration=method_declarations())
@settings(
    max_examples=80,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_registry_property_checks_random_valid_and_invalid_declarations(
    declaration: dict[str, Any],
) -> None:
    class GeneratedMethod:
        name = declaration["name"]
        params_type = EmptyParams
        required_inputs = tuple(declaration["required_inputs"])
        output = OutputSpec(
            fields=tuple(OutputField(path) for path in declaration["output_fields"]),
            panel=PanelSpec(
                id="generated",
                title="Generated",
                kind="summary",
                field=declaration["output_fields"][0] if declaration["output_fields"] else "",
            ),
        )

        def compute(self, dataset: Dataset, params: EmptyParams) -> dict[str, Any]:
            return _result_for_paths(declaration["output_fields"])

    registry = MethodRegistry()
    well_formed = (
        bool(declaration["name"].strip())
        and bool(declaration["output_fields"])
        and all(_path_is_well_formed(path) for path in declaration["required_inputs"])
        and all(_path_is_well_formed(path) for path in declaration["output_fields"])
    )

    if not well_formed:
        with pytest.raises(MethodDeclarationError):
            registry.register(GeneratedMethod())
        return

    registry.register(GeneratedMethod())
    input_paths_exist = all(path in VALID_INPUT_PATHS for path in declaration["required_inputs"])
    if input_paths_exist:
        run = registry.run(declaration["name"], load_golden())
        assert all(has_field_path(run.result, path) for path in declaration["output_fields"])
    else:
        with pytest.raises(MethodExecutionError):
            registry.run(declaration["name"], load_golden())


def _path_is_well_formed(path: str) -> bool:
    parts = path.split(".")
    return bool(path) and all(parts) and parts == [part.strip() for part in parts]


def test_registry_does_not_mutate_input_dataset_mapping() -> None:
    dataset = load_golden()
    before = copy.deepcopy(dataset)
    registry = MethodRegistry()
    registry.register(band_power_summary)

    registry.run("band_power_summary", dataset)

    assert dataset == before
