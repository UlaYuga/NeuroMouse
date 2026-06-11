# NeuroMouse Architecture

## Pinned Tree

```text
contracts/
packages/core/
packages/backend/
packages/adapters/
packages/sdk/
packages/sdk-ts/
packages/web/
methods/
datasets/golden/
bench/
tests/integration/
infra/
docs/
```

## Packages

`contracts` is the executable data contract. It owns shared data-shape definitions,
validation entrypoints, and compatibility checks. `DATA_CONTRACT.md` remains the source of
truth for data shapes, and this package is where those rules become runnable.

`packages/core` is the signal-processing and method platform layer. It owns DSP primitives,
feature extraction, and the method registry/plugin SDK used to discover and execute analysis
methods consistently.

`packages/backend` is the future service boundary. It will own FastAPI REST and WebSocket APIs,
background jobs, storage integration, and orchestration for browser, SDK, and method workloads.

`packages/adapters` is the signal acquisition layer. It will normalize live devices, file-backed
streams, replay sources, and external neurodata providers into the contracts expected by core.

`packages/sdk` is the Python method-author API. It will give researchers and plugin authors a
stable way to define methods, validate inputs, run locally, and package work for NeuroMouse.

`packages/sdk-ts` is the future TypeScript SDK workspace. It will expose browser and Node-facing
APIs for consuming NeuroMouse contracts and backend endpoints.

`packages/web` is the future frontend workspace. It will eventually replace or wrap the current
zero-build root viewer without breaking the existing app during the transition.

## Rules Of The Road

Every Python package uses uv, pytest, ruff, and ty. Every task is test-first: write the failing
test, prove it fails, implement the smallest passing change, and keep the workspace green.
`datasets/golden` is sacred: never edit frozen goldens in place. `DATA_CONTRACT.md` is the source
of truth for data shapes.
