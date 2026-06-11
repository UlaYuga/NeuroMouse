# MEA Quickstart

This guide is for wetware scientists working with MEA, organoid, cultured-neuron, or
neural-cell recording data. The goal is to get a lab export into the NeuroMouse contract, run
MEA-relevant methods, and keep your own spike sorter or analysis pipeline in the loop.

NeuroMouse is not trying to replace your acquisition software, SpikeInterface pipeline,
vendor sorter, or lab notebook. It gives those tools a stable contract and browser artifact
so collaborators can inspect the same dataset and method outputs.

## Mental Model

```text
MEA recording -> canonical dataset -> declared methods -> browser artifact
```

- Acquisition stays in your lab stack.
- NeuroMouse adapters normalize into a canonical `data.json` shape.
- Methods declare the fields they consume and the outputs they produce.
- The browser renders the canonical dataset and method outputs without asking reviewers to
  run Python.

The contract is montage-agnostic and channel-major. `meta.channels` is the source of channel
order, and every per-channel array uses that same order. The default ceiling is 4096 channels,
which is a safety limit rather than a scientific claim about MEA size. See the
[data contract](../DATA_CONTRACT.md) and
[montage ADR](adr/0004-montage-agnostic-channel-ceiling.md).

## 1. Load MEA Data

The fastest path is a channel-per-column CSV:

```csv
time_sec,MEA-0000,MEA-0001,MEA-0002
0.000000,0.012,-0.004,0.008
0.004000,0.015,-0.003,0.007
```

Then normalize and validate it:

```python
from pathlib import Path

from neuromouse_adapters import read_file
from neuromouse_contract import validate_dataset

source = Path("exports/well-a1.csv")
dataset = validate_dataset(read_file(source))

print(dataset.meta.n_channels)
print(dataset.meta.channels[:5])
```

`read_file()` currently supports CSV, EDF, and BDF replay files. For a wetware export that
already contains PSD or feature tables, emit canonical `data.json` directly using the shape
in [DATA_CONTRACT.md](../DATA_CONTRACT.md). That is usually less fragile than translating a
large MEA export through multiple CSV conventions.

Required canonical fields:

- `meta.channels`: electrode, well, or unit names in display order.
- `welch_psd.frequencies` and `welch_psd.psd`: channel-major power spectra.
- `centroid.time_relative` and `centroid.values`: channel-major centroid time series.
- `geometry.time`: time axis for derived spectral metrics.

Optional fields can carry lab-specific context, sorter provenance, well IDs, stimulation
epochs, culture age, batch labels, or assay notes. Unknown fields are allowed by the Python
contract so long as the hard validation rules pass.

## 2. Run MEA Methods

MEA methods should be ordinary NeuroMouse methods: declaration-first, deterministic, and
registered through the method registry. For wetware work, the first method names should be:

- `spike_detect`: convert sorter output or thresholded events into comparable spike rows.
- `network_burst`: summarize synchronized population bursts and burst windows.
- `connectivity`: produce pairwise or grouped connectivity tables from spikes or features.

The registry contract is described in [Method Authoring](METHOD_AUTHORING.md). The concrete
API lives in
[`MethodRegistry`](../packages/core/src/neuromouse_core/method_registry.py), with the SDK
surface in [`packages/sdk`](../packages/sdk).

The run shape should look like this:

```python
from neuromouse_adapters import read_file
from neuromouse_contract import validate_dataset
from neuromouse_core.method_registry import MethodRegistry

# Import Method objects from the MEA method package when those methods are present.
# The exact implementation can call SpikeInterface, SciPy, NumPy, or lab code internally.
from methods.connectivity import method as connectivity
from methods.network_burst import method as network_burst
from methods.spike_detect import method as spike_detect

dataset = validate_dataset(read_file("exports/well-a1.csv"))

registry = MethodRegistry()
for method in (spike_detect, network_burst, connectivity):
    registry.register(method)

spikes = registry.run("spike_detect", dataset, params={"threshold_uV": 5.0})
bursts = registry.run("network_burst", dataset, params={"min_channels": 8})
network = registry.run("connectivity", dataset, params={"window_ms": 50})
```

Each method should declare:

- the canonical inputs it needs, such as `meta.channels`, `welch_psd.psd`, or a sorter output
  namespace;
- typed params with lab-relevant units;
- output fields under a stable root key, for example `spike_detect.events`;
- a panel hint when the output has a useful table or chart surface.

## 3. Plug In Your Own Sorter

The expected model is "templates plus bring your own sorter." Use NeuroMouse templates and
registry validation for the platform boundary, but keep the sorter you trust.

Recommended boundary:

```text
packages/sorting/
|-- README.md
|-- src/
|   `-- neuromouse_sorting/
|       |-- spikeinterface_adapter.py
|       |-- vendor_export_adapter.py
|       `-- schema.py
`-- tests/
```

`packages/sorting` is the intended home for sorter wrappers once that package is present in
the workspace. Until it lands, keep sorter code in your lab package and expose a small
adapter that returns JSON-serializable outputs to a NeuroMouse method.

A sorter adapter should return stable rows, not opaque objects:

```python
[
    {"channel": "MEA-0007", "time_sec": 12.304, "amplitude_uV": 41.2, "unit_id": "u03"},
    {"channel": "MEA-0042", "time_sec": 12.307, "amplitude_uV": 38.5, "unit_id": "u11"},
]
```

That output can then become `spike_detect.events`, which `network_burst` and `connectivity`
can consume through declared method inputs.

## 4. What To Capture For Collaborators

For FinalSpark, Cortical Labs, or similar wetware review, keep provenance explicit:

- acquisition system, plate or MEA identifier, well, culture age, and sampling rate;
- preprocessing choices such as filtering, referencing, and dead-channel handling;
- sorter name, version, parameters, and manual curation status;
- stimulation epochs or assay windows if they affect interpretation;
- method params and random seeds for any stochastic step.

The browser artifact should answer three questions quickly:

1. What was recorded?
2. Which method produced each result?
3. Can another scientist rerun or replace the sorter without changing the artifact contract?

## 5. Where To Go Next

- Use [DATA_CONTRACT.md](../DATA_CONTRACT.md) when emitting canonical `data.json`.
- Use [Method Authoring](METHOD_AUTHORING.md) when writing `spike_detect`,
  `network_burst`, or `connectivity`.
- Use [ADR 0007](adr/0007-wetware-mea-direction.md) for the platform direction and why MEA
  is the foreground path.
- Use [`packages/adapters`](../packages/adapters) for replay normalization examples.
- Use `packages/sorting` as the sorter-wrapper target once that package exists in this
  workspace.
