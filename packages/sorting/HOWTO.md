# Adding a Spike Sorter

`neuromouse-sorting` exposes the same shape as the method registry: declare a sorter,
register it, then run it on an `MEARecording`.

```python
from dataclasses import dataclass

from neuromouse_sorting import (
    MEARecording,
    OutputField,
    SortedUnit,
    SorterOutputSpec,
    SortingResult,
    SpikeSorterRegistry,
)


@dataclass(frozen=True)
class MySorterParams:
    threshold: float = 5.0


class MySorter:
    name = "my-sorter"
    version = "0.1.0"
    params_type = MySorterParams
    output = SorterOutputSpec(
        fields=(
            OutputField("units"),
            OutputField("metadata.sorter"),
            OutputField("metadata.n_spikes"),
        )
    )

    def sort(self, recording: MEARecording, params: MySorterParams) -> SortingResult:
        units = []
        for channel, samples in zip(recording.channels, recording.traces, strict=True):
            spike_indexes = tuple(
                index for index, value in enumerate(samples) if value <= -params.threshold
            )
            if not spike_indexes:
                continue
            units.append(
                SortedUnit(
                    unit_id=f"{channel}:my-sorter",
                    channel=channel,
                    spike_sample_indexes=spike_indexes,
                    spike_times_sec=tuple(
                        index / recording.sampling_rate_hz for index in spike_indexes
                    ),
                    metadata={},
                )
            )

        return SortingResult(
            units=tuple(units),
            metadata={
                "sorter": self.name,
                "n_spikes": sum(len(unit.spike_sample_indexes) for unit in units),
            },
        )


registry = SpikeSorterRegistry()
registry.register(MySorter())
run = registry.run("my-sorter", recording, params={"threshold": 6.0})
```

Use `SpikeInterfaceSorter("kilosort4")` when SpikeInterface is installed and you
want NeuroMouse to delegate to a SpikeInterface sorter without making it a hard
dependency for the base package.
