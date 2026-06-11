# ADR 0003: Method SDK Plugin Surface

## Status

Accepted.

## Context

NeuroMouse needs third-party and collaborator-authored methods without turning every method
into a custom backend endpoint or UI patch. Method authors need a small surface that can be
tested, registered, and rendered.

The working example is
[`band_power_summary.py`](../../packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py).
The copyable template is
[`method_template.py`](../../packages/sdk/templates/method_template.py).

## Decision

Use a declaration-first Python method SDK. A method declares:

- `name`
- `params_type`
- `required_inputs`
- `output.fields`
- optional `output.panel`
- `compute(dataset, params)`

Methods run through
[`MethodRegistry`](../../packages/core/src/neuromouse_core/method_registry.py), which
validates inputs, params, output fields, and panel references.

## Consequences

- Method outputs become inspectable artifacts instead of hidden script conventions.
- UI integration can start from declared panel metadata.
- Registry tests can catch missing inputs and undeclared outputs.
- Complex methods can still call MNE, SpikeInterface, SciPy, or lab code internally as long
  as their NeuroMouse boundary is declared.
