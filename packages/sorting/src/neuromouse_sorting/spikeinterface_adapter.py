from __future__ import annotations

import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

from neuromouse_sorting.models import (
    MEARecording,
    OutputField,
    SortedUnit,
    SorterOutputSpec,
    SortingResult,
)
from neuromouse_sorting.registry import SpikeSorterExecutionError


@dataclass(frozen=True)
class SpikeInterfaceSorterParams:
    sorter_params: Mapping[str, Any] = field(default_factory=dict)
    output_folder: str | None = None
    remove_existing_folder: bool = True


class SpikeInterfaceSorter:
    version = "0.1.0"
    params_type = SpikeInterfaceSorterParams
    output = SorterOutputSpec(
        fields=(
            OutputField("units", "Units returned by SpikeInterface"),
            OutputField("metadata.sorter", "SpikeInterface sorter adapter name"),
            OutputField("metadata.version", "Adapter version"),
            OutputField("metadata.spikeinterface_sorter", "Delegated SpikeInterface sorter"),
            OutputField("metadata.n_units", "Number of units returned"),
            OutputField("metadata.n_spikes", "Total returned spike count"),
        )
    )

    def __init__(self, sorter_name: str, *, name: str | None = None) -> None:
        self.sorter_name = sorter_name.strip()
        if not self.sorter_name:
            raise ValueError("sorter_name must be a non-empty string")
        self.name = name or f"spikeinterface:{self.sorter_name}"

    @property
    def available(self) -> bool:
        return _module_available("spikeinterface") and _module_available("spikeinterface.sorters")

    @property
    def unavailable_reason(self) -> str:
        if self.available:
            return ""
        return "SpikeInterface is not installed; install neuromouse-sorting[spikeinterface]"

    def sort(self, recording: MEARecording, params: SpikeInterfaceSorterParams) -> SortingResult:
        if not self.available:
            raise SpikeSorterExecutionError(self.unavailable_reason)

        import numpy as np

        si = import_module("spikeinterface")
        se = import_module("spikeinterface.extractors")
        ss = import_module("spikeinterface.sorters")

        traces = np.asarray(recording.traces, dtype=np.float32).T
        si_recording = _numpy_recording(
            spikeinterface=si,
            extractors=se,
            traces=traces,
            sampling_rate_hz=recording.sampling_rate_hz,
            channels=recording.channels,
        )
        sorting = ss.run_sorter(
            self.sorter_name,
            si_recording,
            output_folder=params.output_folder,
            remove_existing_folder=params.remove_existing_folder,
            **dict(params.sorter_params),
        )

        units: list[SortedUnit] = []
        for unit_id in sorting.get_unit_ids():
            sample_indexes = tuple(
                int(index) for index in sorting.get_unit_spike_train(unit_id=unit_id)
            )
            units.append(
                SortedUnit(
                    unit_id=str(unit_id),
                    channel="unassigned",
                    spike_sample_indexes=sample_indexes,
                    spike_times_sec=tuple(
                        index / recording.sampling_rate_hz for index in sample_indexes
                    ),
                    metadata={"spikeinterface_unit_id": unit_id},
                )
            )

        return SortingResult(
            units=tuple(units),
            metadata={
                "sorter": self.name,
                "version": self.version,
                "spikeinterface_sorter": self.sorter_name,
                "n_units": len(units),
                "n_spikes": sum(len(unit.spike_sample_indexes) for unit in units),
            },
        )


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _numpy_recording(
    *,
    spikeinterface: Any,
    extractors: Any,
    traces: Any,
    sampling_rate_hz: float,
    channels: Sequence[str],
) -> Any:
    kwargs = {
        "traces_list": [traces],
        "sampling_frequency": sampling_rate_hz,
        "channel_ids": list(channels),
    }
    numpy_recording = getattr(extractors, "NumpyRecording", None) or getattr(
        spikeinterface, "NumpyRecording", None
    )
    if numpy_recording is None:
        raise SpikeSorterExecutionError("SpikeInterface NumpyRecording API was not found")
    return numpy_recording(**kwargs)
