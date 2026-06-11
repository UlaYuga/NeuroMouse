# ADR 0007: Wetware And MEA Direction

## Status

Accepted.

## Context

NeuroMouse began with an EEG-oriented browser workbench, but the stronger product direction
is wetware and MEA collaboration. FinalSpark, Cortical Labs, and adjacent organoid or
cultured-neuron workflows need reviewable artifacts for dense channel recordings, spike
events, network bursts, and connectivity summaries. They also need to keep their existing
recorders, sorters, notebooks, and scientific validation paths.

The repository already has the platform pieces that make this direction plausible:

- a montage-agnostic, channel-major contract with a 4096-channel default ceiling;
- Python adapters that normalize replay files into canonical datasets;
- a method SDK and registry that validate declared inputs and outputs;
- browser rendering that falls back to generic channel layouts when 10-20 EEG labels do not
  apply.

The risk is positioning NeuroMouse as a generic EEG dashboard or as a replacement for
SpikeInterface, MNE, SciPy, NumPy, vendor sorters, or lab code. That would make the platform
less useful to wetware scientists, who need a neutral coordination layer rather than another
analysis stack to adopt wholesale.

## Decision

Foreground wetware and MEA as the chosen direction. Treat EEG as a valuable compatibility
path and demo source, but optimize the narrative, docs, and method roadmap for MEA-scale
recordings and wetware collaboration.

Keep the core contract montage-agnostic:

- channel identity comes from `meta.channels`;
- per-channel arrays are channel-major in that order;
- 10-20 EEG layout is a rendering convenience, not a data model;
- the 4096-channel default ceiling is a denial-of-service guard, not a scientific boundary.

Use a "templates plus bring-your-own-sorter" model:

- NeuroMouse owns the executable contract, method declaration surface, registry validation,
  provenance expectations, and browser artifact.
- Labs keep their validated sorter or spike pipeline.
- Sorter wrappers should live behind a narrow package boundary, with `packages/sorting` as
  the intended workspace home once that package is added.
- Wetware methods should expose stable outputs under declared method roots, starting with
  `spike_detect`, `network_burst`, and `connectivity`.

## Consequences

- Docs should lead with MEA, organoid, cultured-neuron, and wetware workflows instead of
  framing MEA as a future appendix to EEG.
- New examples should use electrode, well, and MEA-style channel names when the concept does
  not require EEG-specific labels.
- UI and service code must continue to reject hardcoded 32-channel assumptions except where
  they are explicit demo defaults.
- Method authors can call SpikeInterface, MNE, SciPy, NumPy, vendor exports, or lab code
  internally, but the NeuroMouse boundary remains declared inputs, typed params, declared
  outputs, and provenance.
- The sorter boundary stays replaceable. A lab can swap sorting implementations without
  changing the artifact contract if the method output schema remains stable.
- Bench and fuzz work should keep MEA-scale payloads in view because dense wetware data is
  the workload that justifies the platform.
