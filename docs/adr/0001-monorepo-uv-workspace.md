# ADR 0001: Monorepo And uv Workspace

## Status

Accepted.

## Context

NeuroMouse needs one place where the browser viewer, executable contract, adapters, backend,
core method registry, and SDK can evolve together. Splitting these too early would make the
contract drift across repos and make collaborator demos harder to reproduce.

The repository now has a root [`pyproject.toml`](../../pyproject.toml) with a `uv`
workspace for:

- [`contracts`](../../contracts)
- [`packages/adapters`](../../packages/adapters)
- [`packages/backend`](../../packages/backend)
- [`packages/core`](../../packages/core)
- [`packages/sdk`](../../packages/sdk)

The root JavaScript viewer remains in place while Python platform packages are added beside
it.

## Decision

Use a monorepo with a `uv` workspace for Python packages and keep the zero-build browser app
in the same repository until the frontend workspace is real.

## Consequences

- Contract, SDK, backend, and viewer changes can be reviewed in one branch.
- Python package imports can be tested together with one `uv run pytest`.
- The root viewer can keep serving collaborators while platform packages mature.
- Package boundaries still matter: shared behavior belongs in `contracts`, `core`, `sdk`,
  `adapters`, or `backend`, not in ad hoc scripts.
