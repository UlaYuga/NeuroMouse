# NeuroMouse — Architecture & Production-Readiness Critique

**Scope.** Hard, adversarial review of the repository as of `main @ 009fc63`: package
layout, the data contract, the run-engine, the FastAPI backend (jobs / storage / WS),
deploy-readiness (`Dockerfile`, `infra/`, `.github/workflows/ci.yml`), and the plugin/method
+ sorter seams. Read-only to code; `dsp.py` untouched. Produced by a completeness-critic
loop (rounds logged at the end).

**One-line verdict.** The *engineering core* (executable contract, declaration-first method
registry, reproducibility manifest, fuzz-gated CI) is genuinely strong and above the bar for
a research tool. The *production platform* the docs and positioning describe **does not yet
ship**: the entire Python backend is undeployed, the one outward HTTP surface that *is*
deployed (`/api/explain`) is an unauthenticated cost-and-data-egress liability, and the
backend's execution/storage model is not production-shaped. The gap is between "what is
built and tested" and "what is wired to run in front of users."

---

## How to read this

Findings are prioritized by blast radius against the **stated** goal — a hosted,
demo-able, plugin-first platform (`COORDINATOR.md §8`, `REPOSITORY_METADATA.md`,
`README` "Production: …up.railway.app").

- **P0** — blocks the stated production goal or is an active liability on the live host.
- **P1** — will fail under real (even light) multi-user / real-data load.
- **P2** — hardening, drift, and operability debt to schedule before scale.

If the *actual* near-term goal is only "static viewer + a demo screenshot," then P0-1 and
several P1s are not blockers — they are the cost of the next step. That ambiguity is itself
the most important thing to resolve (see **Strategic note** at the end).

---

## P0 — Ship-blockers / live liabilities

### P0-1 · The backend platform is not deployable — only the static viewer ships
`Dockerfile` copies **only** the Node static runtime:

```dockerfile
COPY package.json server.mjs ./
COPY index.html style.css ./
COPY data ./data
COPY js ./js
COPY assets ./assets
CMD ["node", "server.mjs"]
```

The whole `packages/backend` FastAPI service — sessions, jobs, SQLite storage, method
catalog, sorter seam, WebSockets — has **no** container target, **no** process manager, **no**
Railway service definition, and **no** compose file. `infra/` is a one-line placeholder
README. The only place the backend is started anywhere in the repo is the `make dev` helper
(`uvicorn … --reload`, dev-only). `SECURITY.md` even ratifies this: *"The production
deployment (Railway) serves only the pre-built static assets … No database and no
user-authentication surface exist."*

Consequence: every Wave-2/Wave-3 deliverable (jobs, run manifests, MEA sorter, demo seed
endpoints) is **dead on the production host**. The architecture is two runtimes
(Node + Python) but only one is wired to ship, and the docs (`docs/ARCHITECTURE.md` "service
boundary", "the next service layer") describe an aspiration, not the deployed system.

**Fix:** decide the deployment topology explicitly. Either (a) a second Railway service with
its own `Dockerfile` (`uvicorn`/`gunicorn`-`uvicorn-worker`, pinned, `HEALTHCHECK`, mounted
volume) fronted so the viewer can reach it, or (b) consciously declare the backend
out-of-scope for this deploy and stop describing it as the production service layer. Record
the choice as an ADR.

### P0-2 · `/api/explain` is an open, unauthenticated key-burning + data-egress endpoint
`server.mjs:93-181`. The single dynamic surface that *is* live:

- **No auth, no rate limit, no per-IP budget.** Anyone who can reach the production URL can
  POST to `/api/explain` and cause the server to spend the operator's LLM credits. This is a
  direct financial-DoS on a public endpoint.
- **Third-party egress by default.** Default upstream is
  `process.env.EXPLAIN_API_URL ?? "https://api.kie.ai/claude/v1/messages"` — a *third-party
  gateway*, not the Anthropic API — and the server forwards `ANTHROPIC_API_KEY` to it as a
  `Bearer` token. A non-Anthropic host receives a key named `ANTHROPIC_API_KEY`.
- **Contradicts the stated threat model.** The request body is the user's analysis context
  (derived neural-signal numbers), forwarded off-box. `SECURITY.md` claims *"No neural data
  is transmitted to any cloud service … data never leaves the browser session."* The explain
  path violates that the moment it is configured.

**Fix:** gate behind auth or a server-side per-session/global budget + rate limiter; default
`EXPLAIN_API_URL` to the official Anthropic endpoint (or fail closed if unset); rename/scope
the credential to the actual upstream; and reconcile `SECURITY.md` with the fact that explain
*does* egress derived data. At minimum document that enabling explain breaks the local-only
guarantee.

---

## P1 — Will not survive real load / real data

### P1-1 · Method execution blocks the event loop; "queued/running" is theater
`app.py:231-261`. `create_job` runs the method **synchronously, inline, in an `async def`
handler**:

```python
backend_store.append_job_event(job.id, status="running")
result = jsonable_encoder(methods.run(request.method_id, session.dataset, params=...))
```

`methods.run` is CPU-bound NumPy/SciPy. There is no `run_in_threadpool`, `asyncio.to_thread`,
or worker queue anywhere in `packages/backend/src` (grep-confirmed). A single heavy job (and
HD-MEA is the headline use-case) **stalls the entire Uvicorn event loop** — every other
request and WebSocket blocks until it returns.

The job lifecycle is also cosmetic: `queued → running → completed` events are all written in
one synchronous breath; there is no real queue and nothing is ever actually "queued." The
progress WebSocket (`app.py:282-292`) just **replays already-stored events and closes** — it
is not a live progress channel. A client connecting after completion gets a historical dump;
a client connecting before gets nothing streamed. This is "fail-fast and synchronous"
dressed as async job orchestration.

**Fix:** offload compute (threadpool for CPU-bound, or a real task queue/worker for anything
long), make the WS subscribe to a live event stream (pub/sub or polling the store), and
enforce a per-job timeout. If synchronous is acceptable for the demo, drop the queue/WS
fiction and document it as synchronous-only.

### P1-2 · SQLite model is not deploy-shaped; data loss on the target host
`storage.py:160-200, 393-401`.

- **Single shared connection + `RLock`** (`check_same_thread=False`) serializes *all*
  reads and writes through one lock → effective write concurrency of 1, and reads contend
  with writes. No `WAL` pragma, no pooling, no busy-timeout.
- **Default DB path is relative to CWD** (`"neuromouse_backend.sqlite3"`). On Railway's
  ephemeral container filesystem with **no mounted volume**, the database is wiped on every
  redeploy/restart. (Moot today only because the backend isn't deployed — P0-1 — but it is a
  latent data-loss bug the moment it is.)
- **Schema migration is `CREATE TABLE IF NOT EXISTS` only.** There is no version table and no
  migration path; any future column change has no upgrade story.
- **Whole dataset stored as a single JSON `TEXT` blob** and fully re-materialized on every
  `get_session`/`list_sessions` (`_load_json`). Combined with P1-3 this is a memory and I/O
  cliff for large datasets.

**Fix:** per-request connections or a pool, `WAL` + `busy_timeout`, an absolute
volume-backed path with a documented `NEUROMOUSE_BACKEND_DB`, a real migration mechanism, and
a size guard before persisting a dataset.

### P1-3 · Unbounded array sizes = memory DoS across every layer
`contracts/src/neuromouse_contract/dataset.py`. The contract caps **channel count** (4096,
`DEFAULT_MAX_CHANNELS`) but places **no ceiling on array lengths**: `welch_psd.frequencies`,
`centroid.time_relative`, `geometry.time`, and especially `mea.traces` row length are all
unbounded. A `4096 × N` matrix with a large `N` passes validation and is then fully
materialized in: the browser (`static-source.js`), Pydantic, the SQLite `TEXT` column, and
`content_hash` (`model_dump(mode="json")` over the whole thing). `ContractModel` also sets
`extra="allow"` (`dataset.py:27-28`), so arbitrary unmodelled keys are accepted, stored, and
echoed back — payload size and shape are attacker-controlled. FastAPI has **no request body
size limit** configured.

The DoS ceiling the contract advertises is therefore only half-built: it bounds one
dimension of the matrix and leaves the other (and total bytes) open.

**Fix:** add a total-elements / total-bytes budget to `validate_dataset`, bound trace and
axis lengths, and put a body-size limit in front of the FastAPI app. Reconsider
`extra="allow"` for the top-level dataset (or cap/strip unknown keys).

### P1-4 · Plugin & sorter code runs in-process, unsandboxed — the core unsolved problem
`method_registry._execute` (`method_registry.py:297-323`) and
`sorting/registry.run` call user-supplied `compute()` / `sort()` **directly in the backend
process**. The platform's entire pitch — *"plugging a method/sorter in is trivial (~50 lines
→ a live panel)," BYO-sorter* (`COORDINATOR.md §8`) — means **third-party Python executing
inside the service** with:

- no sandbox / process isolation,
- no CPU/memory/wall-clock limit (a method can hang or OOM the whole server — see P1-1),
- no capability restriction (a method can read the filesystem, open sockets, exfiltrate other
  sessions' data).

The registry validates *declared input/output field paths* well, but a declaration says
nothing about what the body does. For a single-tenant research tool this is acceptable and
worth stating plainly; for the "Hugging Face layer for neural data" positioning (multi-author,
shared host) it is the central security problem and it is currently unaddressed.

**Fix (scaled to ambition):** for now, document the trust boundary ("methods are trusted
code; do not run untrusted plugins on a shared host") and add a per-run timeout. For the
platform vision, this needs real isolation (subprocess with rlimits, container/gVisor, or
WASM) before any third-party method is accepted.

---

## P2 — Hardening, drift, operability

| # | Finding | Where | Note |
|---|---------|-------|------|
| P2-1 | **No auth / CORS / rate-limit / security headers** on FastAPI | `app.py` (no middleware, grep-confirmed) | Even internal services should set CORS allowlist + body limits before exposure. |
| P2-2 | **No backend observability** | `app.py`, `Dockerfile` | No structured logging, request IDs, metrics, or backend `/healthz`; `Dockerfile` has no `HEALTHCHECK`. Only the Node server has `/healthz`. |
| P2-3 | **Contract sync has no CI guard for the TS layer** | `.github/workflows/ci.yml` | Good: `test_dataset_contract.py:589` asserts on-disk schema == `model_json_schema()`, and Python↔JS parity is tested; `mea` is present in **all four** validators (pydantic, JSON schema, TS `schema.ts`, JS `static-source.js`) — sync is *actually maintained*. Gap: CI never regenerates `sdk-ts` types from the schema and diffs, so TS can silently drift from a hand-edit. Add a "regenerate + `git diff --exit-code`" step. |
| P2-4 | **Supply chain** | `SECURITY.md`, CI | JSZip is CDN trust-on-first-use with no SRI; no dependency scanning / SBOM / `pip-audit` / Dependabot in CI. `SECURITY.md` recommends SRI but the app does not implement it. |
| P2-5 | **Two-runtime integration is unspecified** | `server.mjs`, `app.py`, `DATA_CONTRACT.md §3` | The viewer's live WS contract is `ws://127.0.0.1:8766`; the FastAPI live endpoint is `/ws/live` (a bare echo). Nothing documents how the browser viewer is meant to reach the FastAPI backend (sessions/jobs) in production — the two halves don't connect. |
| P2-6 | **No graceful shutdown / lifespan** | `storage.py:167` | `SQLiteBackendStore.close()` exists but is never wired to a FastAPI lifespan/shutdown hook; the connection leaks on restart. |
| P2-7 | **Operational scaffolding missing** | repo root | No `.env.example` documenting `ANTHROPIC_API_KEY` / `EXPLAIN_API_URL` / `EXPLAIN_MODEL` / `NEUROMOUSE_BACKEND_DB` / `PORT`; no backup story; no documented single-replica constraint (SQLite forbids horizontal scale-out). |
| P2-8 | **`/ws/live` echo is an unbounded open socket** | `app.py:306-314` | Accepts any client, echoes JSON forever, no auth/size/rate limit. Harmless while undeployed; a footgun if the backend ships. |
| P2-9 | **`bench/` perf gate is informational only** | `ci.yml:99-102` | `continue-on-error: true` and only `--help`. There is no perf regression guard despite an MEA-perf workstream; p95 budgets aren't enforced anywhere. |

---

## What is genuinely good (keep / defend)

- **Executable contract as the spine.** One Pydantic source of truth, emitted to JSON Schema,
  codegen'd into TS, parity-tested against the JS validator, and fuzzed from two sides
  (`validate-data`, `import-csv-zip`). The `mea` block being consistently present across all
  four validators shows the "4 places" discipline is actually being held.
- **Declaration-first registries.** `method_registry` and `sorting/registry` refuse missing
  inputs and undeclared outputs, validate panel/field references, and treat the dataset as
  immutable input. This is a clean, testable plugin seam.
- **Reproducibility manifest.** `RunManifest` (content hash + seed + library/platform
  versions + output hash + self-checking `run_id`) with `verify_reproduction` is a strong,
  research-credible feature most tools lack. Canonical JSON with `allow_nan=False` is the
  right call.
- **Fuzz-gated, matrixed CI.** Linux gate across py3.11/3.12, ruff + ty as hard gates,
  bounded property + deep fuzz suites, TS `tsc --noEmit`. The structural fix for the macOS
  dlopen quirk (CI-on-Linux) is the right one.
- **Montage-agnostic design.** Channels-as-data (not constants), graceful optional-field
  degradation, and the 10-20-or-generic fallback are well thought through.

---

## Production-readiness checklist

| Capability | Status | Gap → action |
|---|---|---|
| Static viewer deploys | ✅ | `Dockerfile` + `server.mjs` + `/healthz` are fine. |
| Backend deploys | 🔴 | **P0-1** — no container/service/volume. Decide topology or descope. |
| Secrets & egress safety | 🔴 | **P0-2** — open `/api/explain`, third-party key forward, threat-model contradiction. |
| Concurrency / job model | 🔴 | **P1-1** — event-loop-blocking sync compute; fake queue/WS. |
| Durable storage | 🔴 | **P1-2** — single-conn SQLite, ephemeral path, no migrations. |
| Input-size safety | 🟡 | **P1-3** — channel cap only; array/byte sizes + `extra="allow"` unbounded. |
| Plugin trust boundary | 🔴 | **P1-4** — unsandboxed in-process user code; no timeout. |
| AuthN/Z, CORS, rate-limit | 🔴 | **P2-1** — none on FastAPI. |
| Observability / healthcheck (backend) | 🔴 | **P2-2** — no logs/metrics/health; no `HEALTHCHECK`. |
| Contract integrity | ✅ | Schema/parity tests solid; add TS-regen diff in CI (**P2-3**). |
| Supply-chain hygiene | 🟡 | **P2-4** — SRI/SBOM/dep-scan absent. |
| Reproducibility | ✅ | `RunManifest` + `verify_reproduction`. |
| Perf regression guard | 🟡 | **P2-9** — bench is informational only. |
| Backups / scale-out | 🔴 | SQLite single-writer; no backup; single-replica only (**P2-7**). |

---

## Strategic note — resolve the goal ambiguity first

Most P0/P1 severity hinges on **one undecided question**: is the near-term deliverable a
*hosted multi-user platform* or a *single-tenant research workbench + demo*? The repo is
ambitious in its docs (platform, BYO-sorter, "Hugging Face layer") but conservative in what it
actually ships (static viewer). Pick one and align:

- **If platform:** P0-1, P0-2, P1-1, P1-2, P1-4 are all real blockers and the backend needs a
  genuine service architecture (queue/worker, Postgres or volume-backed SQLite, sandboxed
  execution, auth) before any outside user or third-party method touches it.
- **If workbench + demo:** keep the backend explicitly local/dev, fix P0-2 (it's live
  regardless), bound payloads (P1-3), and **stop documenting the backend as the production
  service layer** so the gap stops reading as a bug. A one-paragraph "deployment scope" ADR
  closes most of the perceived risk for free.

The engineering substrate is good enough that either path is achievable; the risk today is
narrative drift between them, which is exactly the kind of compose-gap `COORDINATOR.md §7`
warns about — here between *built* and *deployed* rather than between two parallel tasks.

---

## Completeness-critic rounds (log)

- **Round 1 — layer sweep.** Walked packages, contract, run-engine, backend, deploy, seams.
  *Gap surfaced:* the backend has no deploy target; the only live dynamic surface is
  `/api/explain`. → P0-1, P0-2.
- **Round 2 — production risks.** Asked "what breaks under load?" *Gaps:* event-loop-blocking
  synchronous compute; single-connection SQLite; no auth/CORS/limits; unsandboxed plugin
  execution. → P1-1, P1-2, P1-4, P2-1.
- **Round 3 — failure modes.** Asked "what fails silently / loses data / exhausts memory?"
  *Gaps:* WS progress is a replay not a stream; ephemeral DB path → data loss; unbounded array
  sizes + `extra="allow"`; no backend healthcheck/observability. → P1-1 (refined), P1-2
  (refined), P1-3, P2-2.
- **Round 4 — drift & supply chain.** Asked "what silently diverges or is unverified?"
  *Checked* the 4-validator sync directly — found it is **actually maintained** (`mea` present
  in all four; schema parity tested), downgrading the suspected P1 drift to a P2 CI-guard gap.
  *Gaps:* no TS-regen diff in CI; no SRI/SBOM/dep-scan; bench gate informational. → P2-3,
  P2-4, P2-9.
- **Round 5 — integration & operability.** Asked "what's unspecified between the parts?"
  *Gaps:* viewer↔backend wiring undocumented; no lifespan/shutdown; no `.env.example`/backup;
  open `/ws/live` echo. → P2-5..P2-8.
- **Round 6 — convergence check.** Re-asked "any layer not covered, prod risk not named,
  failure mode unhandled?" No **new** material gap surfaced; remaining items were refinements
  of P0-2/P1-1/P1-3 already recorded. **Loop converged at K=2 quiet rounds (5→6).**
</content>
