# ADR 0004: Montage-Agnostic Contract With 4096-Channel Ceiling

## Status

Accepted.

## Context

The early viewer had EEG-shaped assumptions. The platform direction needs to support named
EEG channels, high-density EEG, MEA layouts, and wetware-adjacent data without baking in a
single montage.

The contract now treats `meta.channels` as data. Channel order comes from the dataset, and
per-channel arrays are channel-major in the same order. The executable contract defines
`DEFAULT_MAX_CHANNELS = 4096`.

## Decision

Stay montage-agnostic and use a configurable 4096-channel default ceiling as a safety limit.
The ceiling is a denial-of-service guard, not a scientific claim about supported modalities.

## Consequences

- 10-20 EEG can render with familiar layout when names match.
- Non-10-20 datasets can fall back to generic channel layouts.
- HD-MEA datasets under the ceiling are valid contract targets.
- Callers that need a lower operational ceiling can pass a smaller `max_channels`.
- Any code that assumes 32 channels is a bug unless it is explicitly demo-only metadata.
