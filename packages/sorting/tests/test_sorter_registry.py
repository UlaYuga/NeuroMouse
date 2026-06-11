from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from neuromouse_sorting import (
    MEARecording,
    OutputField,
    SortedUnit,
    SorterOutputSpec,
    SortingResult,
    SpikeSorterDeclarationError,
    SpikeSorterExecutionError,
    SpikeSorterRegistry,
)


@dataclass(frozen=True)
class EmptyParams:
    pass


def recording() -> MEARecording:
    return MEARecording(
        channels=("MEA-1", "MEA-2"),
        sampling_rate_hz=1_000.0,
        traces=((0.0, -7.0, 0.0, 0.0), (0.0, 0.0, -8.0, 0.0)),
        metadata={"fixture": "registry"},
    )


class MissingProtocolFieldSorter:
    name = "missing_protocol_field"
    version = "1.0.0"
    params_type = EmptyParams

    def sort(self, recording: MEARecording, params: EmptyParams) -> SortingResult:
        return SortingResult(units=(), metadata={})


class MissingDeclaredOutputFieldSorter:
    name = "missing_declared_output"
    version = "1.0.0"
    params_type = EmptyParams
    output = SorterOutputSpec(
        fields=(
            OutputField("units"),
            OutputField("metadata.required_quality_metric"),
        )
    )

    def sort(self, recording: MEARecording, params: EmptyParams) -> SortingResult:
        return SortingResult(
            units=(
                SortedUnit(
                    unit_id="unit-1",
                    channel="MEA-1",
                    spike_sample_indexes=(1,),
                    spike_times_sec=(0.001,),
                    metadata={"threshold": -7.0},
                ),
            ),
            metadata={"sorter": self.name},
        )


def test_sorter_missing_a_protocol_field_is_rejected() -> None:
    registry = SpikeSorterRegistry()

    with pytest.raises(SpikeSorterDeclarationError, match="sorter.output"):
        registry.register(cast(Any, MissingProtocolFieldSorter()))


def test_sorter_missing_a_declared_output_field_is_rejected() -> None:
    registry = SpikeSorterRegistry()
    registry.register(MissingDeclaredOutputFieldSorter())

    with pytest.raises(SpikeSorterExecutionError, match="metadata.required_quality_metric"):
        registry.run("missing_declared_output", recording())


VALID_RESULT_PATHS = (
    "units",
    "metadata.sorter",
    "metadata.n_units",
    "metadata.n_spikes",
)
INVALID_DECLARED_PATHS = ("", "metadata..sorter", ".units", "metadata.sorter.")


@st.composite
def sorter_declarations(draw: st.DrawFn) -> dict[str, Any]:
    name = draw(st.sampled_from(["generated", " generated ", "", "   "]))
    output_fields = draw(
        st.lists(
            st.sampled_from(VALID_RESULT_PATHS + INVALID_DECLARED_PATHS),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )
    produced_fields = draw(
        st.lists(
            st.sampled_from(VALID_RESULT_PATHS),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )
    return {
        "name": name,
        "output_fields": output_fields,
        "produced_fields": produced_fields,
    }


def _result_for_fields(fields: list[str]) -> SortingResult:
    metadata: dict[str, Any] = {}
    units: tuple[SortedUnit, ...] = ()
    for path in fields:
        if path == "units":
            units = (
                SortedUnit(
                    unit_id="unit-1",
                    channel="MEA-1",
                    spike_sample_indexes=(1,),
                    spike_times_sec=(0.001,),
                    metadata={},
                ),
            )
        elif path.startswith("metadata."):
            metadata[path.split(".", maxsplit=1)[1]] = 1
    return SortingResult(units=units, metadata=metadata)


@given(declaration=sorter_declarations())
@settings(
    max_examples=80,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_registry_property_checks_random_declarations_and_outputs(
    declaration: dict[str, Any],
) -> None:
    class GeneratedSorter:
        name = declaration["name"]
        version = "1.0.0"
        params_type = EmptyParams
        output = SorterOutputSpec(
            fields=tuple(OutputField(path) for path in declaration["output_fields"])
        )

        def sort(self, recording: MEARecording, params: EmptyParams) -> SortingResult:
            return _result_for_fields(declaration["produced_fields"])

    registry = SpikeSorterRegistry()
    well_formed = (
        bool(declaration["name"].strip())
        and bool(declaration["output_fields"])
        and all(_path_is_well_formed(path) for path in declaration["output_fields"])
    )

    if not well_formed:
        with pytest.raises(SpikeSorterDeclarationError):
            registry.register(GeneratedSorter())
        return

    sorter = GeneratedSorter()
    assert registry.register(sorter) is sorter
    assert registry.lookup(declaration["name"]) is sorter
    assert registry.lookup(f" {declaration['name']} ") is sorter

    missing_fields = [
        path
        for path in declaration["output_fields"]
        if path != "units" and path not in declaration["produced_fields"]
    ]
    if not missing_fields:
        run = registry.run(declaration["name"], recording())
        assert run.sorter_name == declaration["name"].strip()
    else:
        with pytest.raises(SpikeSorterExecutionError):
            registry.run(declaration["name"], recording())


def _path_is_well_formed(path: str) -> bool:
    parts = path.split(".")
    return bool(path) and all(parts) and parts == [part.strip() for part in parts]
