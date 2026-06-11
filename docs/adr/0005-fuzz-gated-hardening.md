# ADR 0005: Fuzz-Gated Hardening

## Status

Accepted.

## Context

NeuroMouse accepts user files, ZIP archives, live WebSocket payloads, and method declarations.
Those surfaces fail in messy ways: missing fields, non-finite values, inconsistent channel
counts, malformed metadata, and payloads that are technically parseable but semantically
unsafe.

The repo already has deterministic tests plus property and fuzz harnesses:

- [`contracts/tests/test_dataset_contract.py`](../../contracts/tests/test_dataset_contract.py)
- [`tests/property/validate-data.property.test.mjs`](../../tests/property/validate-data.property.test.mjs)
- [`tests/property/import-csv-zip.property.test.mjs`](../../tests/property/import-csv-zip.property.test.mjs)
- [`tests/fuzz/live-payload.fuzz.mjs`](../../tests/fuzz/live-payload.fuzz.mjs)
- [`packages/core/tests/test_method_registry.py`](../../packages/core/tests/test_method_registry.py)

## Decision

Use fuzz and property tests as hardening gates for untrusted input surfaces. Keep known
regressions as executable repro cases, then run broader randomized coverage around them.

## Consequences

- Parser robustness is measured by rejected bad inputs and clean errors, not just accepted
  happy paths.
- Live ingestion and browser DSP changes should run at least quick fuzz before review.
- Contract and registry changes need both deterministic tests and generated input coverage.
- Fuzz failures are product findings: they show what a collaborator, device, or file export
  could trigger.
