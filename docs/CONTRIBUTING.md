# Contributing To NeuroMouse

This guide expands the root [CONTRIBUTING.md](../CONTRIBUTING.md) for the docs-site
artifact. Keep changes small, contract-first, and reviewable by collaborators who care about
both science and software reliability.

## Scope Rules

- Keep the existing root viewer stable unless the task explicitly changes UI behavior.
- Treat [DATA_CONTRACT.md](../DATA_CONTRACT.md) as the human contract of record.
- Treat [`contracts/src/neuromouse_contract/dataset.py`](../contracts/src/neuromouse_contract/dataset.py)
  as the executable Python contract.
- Do not edit frozen golden datasets in place.
- Add or update tests before widening inputs, method outputs, or adapter behavior.
- Keep provenance explicit when an adapter emits metadata-only data instead of neural
  samples.

## Usual Verification

Run the smallest useful set for the change, then broaden when shared contracts or ingestion
surfaces move.

```bash
uv run pytest
npm test
(cd tests/property && npm test)
(cd tests/fuzz && npm run fuzz:quick)
(cd packages/sdk-ts && npm test)
```

For docs-only changes, also validate internal links and any SVG assets.

## Method Contributions

New methods should start from the template:

- working example:
  [`band_power_summary.py`](../packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py)
- copyable template:
  [`method_template.py`](../packages/sdk/templates/method_template.py)
- docs guide: [METHOD_AUTHORING.md](METHOD_AUTHORING.md)

Every method must declare:

- stable `name`
- typed `params_type`
- `required_inputs` field paths
- `output.fields`
- optional `output.panel`
- deterministic `compute(dataset, params)` behavior

The registry validates those declarations. If a method needs a field that is not in the
contract yet, make the contract decision first instead of smuggling implicit shapes into the
method result.

## Adapter Contributions

Adapters should normalize acquisition and replay sources into the canonical dataset shape.
Use [`assert_adapter_conforms`](../packages/adapters/src/neuromouse_adapters/conformance.py)
in tests so adapter behavior fails before it reaches the viewer.

Good adapter changes include:

- one narrow fixture or synthetic source
- explicit channel names and sample rate handling
- finite numeric outputs
- stable provenance in `meta.source` and `meta.analysis_by`
- rejection tests for malformed files or impossible metadata

## Documentation Contributions

Documentation should be linkable from [docs/README.md](README.md), short enough to review,
and tied to real files. Prefer ADRs for decisions that affect future contributors and the
architecture guide for current-state maps.
