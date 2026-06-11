# ADR 0002: Executable Data Contract

## Status

Accepted.

## Context

The human contract in [DATA_CONTRACT.md](../../DATA_CONTRACT.md) is necessary but not enough.
Backend, adapter, SDK, TypeScript, and browser paths need the same rules or they will drift.

The current contract implementation uses:

- Pydantic models in [`dataset.py`](../../contracts/src/neuromouse_contract/dataset.py)
- generated JSON Schema in [`dataset.schema.json`](../../contracts/schema/dataset.schema.json)
- TypeScript/AJV consumers in [`packages/sdk-ts`](../../packages/sdk-ts)
- browser validation in [`js/sources/static-source.js`](../../js/sources/static-source.js)

## Decision

Make the data contract executable. The Markdown contract remains the readable source of
record, but every important data-shape rule must also have runnable validation and tests.

## Consequences

- Python adapters and backend sessions reject malformed datasets before rendering.
- TypeScript consumers can validate through JSON Schema instead of hand-written types.
- Browser and Python validation parity can be tested.
- Contract changes require coordinated updates to docs, Pydantic validation, schema output,
  and browser validation.
