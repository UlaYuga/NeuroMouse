# NeuroMouse Docs

This directory is the collaborator-facing documentation artifact for the current
NeuroMouse platform direction.

## Start Here

- [Architecture](ARCHITECTURE.md) - current package map, data flow, and test/fuzz strategy.
- [Positioning](POSITIONING.md) - how NeuroMouse fits above acquisition and analysis tools.
- [Landscape SVG](neuromouse-landscape.svg) - visual map for collaborator conversations.
- [Contributing](CONTRIBUTING.md) - contributor rules, verification, methods, and adapters.
- [Method Authoring](METHOD_AUTHORING.md) - SDK method workflow, example, and template.

## Architecture Decisions

- [ADR 0001: Monorepo and uv workspace](adr/0001-monorepo-uv-workspace.md)
- [ADR 0002: Executable data contract](adr/0002-executable-data-contract.md)
- [ADR 0003: Method SDK plugin surface](adr/0003-method-sdk-plugin-surface.md)
- [ADR 0004: Montage-agnostic contract with 4096-channel ceiling](adr/0004-montage-agnostic-channel-ceiling.md)
- [ADR 0005: Fuzz-gated hardening](adr/0005-fuzz-gated-hardening.md)
- [ADR 0006: uv link-mode clone](adr/0006-uv-link-mode-clone.md)

## Source Anchors

- [Human data contract](../DATA_CONTRACT.md)
- [Pydantic contract implementation](../contracts/src/neuromouse_contract/dataset.py)
- [JSON Schema](../contracts/schema/dataset.schema.json)
- [Band power method example](../packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py)
- [Method template](../packages/sdk/templates/method_template.py)
- [Root viewer README](../README.md)
