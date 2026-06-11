# NeuroMouse Architecture

NeuroMouse is moving from a zero-build browser workbench into a small platform for neural
signal replay, method execution, and collaborator-facing analysis. The current repository
already contains both halves of that transition:

- the production static viewer and Node runtime at the repository root
- a `uv` Python workspace for contracts, adapters, core methods, SDK, and backend

The architectural rule is simple: acquisition and analysis code can change, but every path
must converge on the executable dataset contract before anything is served or rendered.

## Package Map

```text
.
|-- DATA_CONTRACT.md                         # human contract of record
|-- contracts/                               # Pydantic contract and JSON Schema
|   |-- schema/dataset.schema.json
|   `-- src/neuromouse_contract/dataset.py
|-- packages/
|   |-- adapters/                            # acquisition and replay normalization
|   |-- backend/                             # FastAPI sessions, jobs, and WebSockets
|   |-- core/                                # DSP primitives and method registry
|   |-- sdk/                                 # Python method-author surface
|   |-- sdk-ts/                              # generated TypeScript/AJV consumer package
|   `-- web/                                 # placeholder for a future frontend workspace
|-- methods/                                 # future method-plugin home
|-- js/                                      # current zero-build browser app
|-- server.mjs                               # production static runtime
|-- tests/property/                          # JS property tests for loader/contract behavior
`-- tests/fuzz/                              # long-run live payload and DSP fuzz harness
```

### `contracts`

`contracts` turns [DATA_CONTRACT.md](../DATA_CONTRACT.md) into executable validation.
The public Python entrypoint is
[`validate_dataset`](../contracts/src/neuromouse_contract/dataset.py), backed by Pydantic
models and hard validation rules. It also emits
[`contracts/schema/dataset.schema.json`](../contracts/schema/dataset.schema.json), which is
consumed by the TypeScript SDK workspace.

### `packages/adapters`

Adapters normalize external sources into the canonical dataset shape. The current adapters
cover:

- BrainFlow-style synthetic board data via
  [`brainflow_synthetic.py`](../packages/adapters/src/neuromouse_adapters/brainflow_synthetic.py)
- file replay for CSV, EDF, and BDF via
  [`file_replay.py`](../packages/adapters/src/neuromouse_adapters/file_replay.py)
- DANDI catalog ingestion as explicit metadata-only data via
  [`dandi.py`](../packages/adapters/src/neuromouse_adapters/dandi.py)
- adapter conformance checks via
  [`conformance.py`](../packages/adapters/src/neuromouse_adapters/conformance.py)

### `packages/core`

`packages/core` owns reusable analysis and method execution. It includes DSP parity logic in
[`dsp.py`](../packages/core/src/neuromouse_core/dsp.py) and the method registry in
[`method_registry.py`](../packages/core/src/neuromouse_core/method_registry.py). The registry
validates declared inputs, coerces typed params, runs a method, and checks declared output
fields before returning a result.

### `packages/sdk`

`packages/sdk` is the method-author API. It defines the tiny plugin protocol:
`name`, `params_type`, `required_inputs`, `output`, and `compute()`. The concrete
[`band_power_summary`](../packages/sdk/src/neuromouse_sdk/examples/band_power_summary.py)
example and [`method_template.py`](../packages/sdk/templates/method_template.py) are the
authoring references.

### `packages/backend`

`packages/backend` is the service boundary. The current FastAPI app validates datasets on
`POST /sessions`, stores in-memory session/job records, exposes a simple `/methods` list,
runs a summary job, and has WebSocket endpoints for job progress and live ingestion echo.
The implementation is in [`app.py`](../packages/backend/src/neuromouse_backend/app.py).

### `packages/sdk-ts`

`packages/sdk-ts` is the browser/Node consumer package. It generates TypeScript types from
the JSON Schema and validates datasets with AJV. This keeps browser and service consumers
aligned with the same executable contract instead of hand-maintained duplicate types.

### Root Viewer And Runtime

The root app is still the live collaborator surface. [`index.html`](../index.html),
[`style.css`](../style.css), and [`js/`](../js) render saved datasets, ZIP imports, live
WebSocket samples, method-like analysis views, and report export without a frontend build
step. [`server.mjs`](../server.mjs) serves the same static app in production.

## Data Flow

```text
acquire -> contract -> run -> serve -> render
```

### 1. Acquire

Inputs enter through four practical paths:

- curated `data/data.json` for the static demo
- raw or zipped `data.json` and CSV ZIP exports through [`js/loader.js`](../js/loader.js)
- optional live raw frames through [`js/sources/live-source.js`](../js/sources/live-source.js)
- Python adapters that normalize acquisition or replay sources into canonical datasets

Acquisition is deliberately broad. The platform should ingest EEG, high-density MEA, and
wetware-adjacent exports as long as they can be represented as channel-major arrays with
clear provenance.

### 2. Contract

Every acquired dataset must pass the documented shape:

- `meta.channels` is the source of channel count and order
- `welch_psd`, `centroid`, and `geometry` use channel-major arrays
- finite numeric values are required for hard-rendered fields
- `meta.channels.length` defaults to a 4096-channel denial-of-service ceiling

Python validation lives in `neuromouse_contract`. Browser validation lives in
`js/sources/static-source.js`. Contract tests check that those decisions stay aligned.

### 3. Run

There are two execution modes:

- browser-local live DSP in [`js/workers/dsp-worker.js`](../js/workers/dsp-worker.js)
- Python method execution through `neuromouse_core.method_registry`

The method registry is intentionally declaration-first. A method declares what fields it
needs and what fields it returns. The registry refuses to run missing inputs and refuses
undeclared output shapes.

### 4. Serve

The current production path is static serving through `server.mjs`. The backend workspace is
the next service layer: validated sessions, jobs, WebSocket job progress, and live ingestion
boundaries.

### 5. Render

The renderer consumes canonical data only. Saved replay, ZIP import, backend session data,
and live-derived frames all converge on the same viewer structures, so views do not need to
know where a dataset came from.

## Test And Fuzz Strategy

The test strategy is contract-first and adversarial:

- Python package tests run through `uv run pytest`.
- Ruff and ty are configured in [`pyproject.toml`](../pyproject.toml).
- `contracts/tests/test_dataset_contract.py` checks the golden dataset, mutation cases,
  Hypothesis-generated valid datasets, and Python/JS validator parity.
- `packages/core/tests/test_method_registry.py` property-tests method declarations,
  missing input rejection, output-field validation, and input immutability.
- `tests/property/validate-data.property.test.mjs` and
  `tests/property/import-csv-zip.property.test.mjs` use fast-check to stress browser
  validation and ZIP conversion.
- `tests/fuzz/live-payload.fuzz.mjs` runs high-volume live payload and DSP fuzzing, with
  known regressions kept as repro cases.
- `packages/sdk-ts/test/validate-dataset.test.ts` verifies generated TypeScript/AJV
  consumers against the shared schema.

The practical gate is: schema, Python validation, browser validation, method registry, and
live parsing must fail closed with clear errors. New ingestion or method surfaces should add
small deterministic tests first, then property or fuzz coverage when the input shape can be
malformed by users, hardware, or upstream tools.

## Current Constraints

- `packages/web` is a placeholder; the root zero-build app is still the real UI.
- `packages/backend` is a skeleton service, not the only production runtime.
- `methods/` is reserved for method plugins, while the working example currently lives in
  `packages/sdk/src/neuromouse_sdk/examples/`.
- The channel ceiling is a safety default, not a scientific limit.
- Golden data under `datasets/golden` should be treated as frozen compatibility evidence.
