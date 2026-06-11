# Audit v2 — find → refute log

Each candidate was attacked by skeptics (default to REFUTED on doubt). Looped until two
consecutive rounds produced no new survivor.

## Round 1 — primary sweep (backend, contract, run-engine, sorter, server.mjs)

| # | Candidate | Verdict | Killing/keeping argument |
|---|-----------|---------|--------------------------|
| 1 | `/api/explain` unauth + unthrottled LLM proxy | **SURVIVES** (Med) | No auth/rate-limit/CORS; user controls upstream `user` turn; unbounded call count drains key. See V2-01. |
| 2 | Explain output → XSS | REFUTED | `js/viewer.js:794` uses `textContent`, not `innerHTML`. |
| 3 | `server.mjs` path traversal | REFUTED | `normalize`+strip-`..`+`resolve(root,…)`+`startsWith(root)`; `root` ends in sep → no prefix/sibling bypass. |
| 4 | Missing CSP/X-Frame-Options/SRI | **SURVIVES** (Low) | Confirmed absent; clickjack→Explain lever. V2-02. |
| 5 | FastAPI sync work blocks event loop + no size cap | **SURVIVES** (Low, dev-only) | Real, but Python not in prod image. V2-03. |
| 6 | FastAPI SQL injection | REFUTED | `storage.py` fully parameterized. |
| 7 | WS CSWSH (no Origin check) | REFUTED→Info | `/ws/live` echoes only caller data; `/ws/jobs/{uuid4}` unguessable + no listing; not in prod image. |
| 8 | Run-engine unsafe deserialization / cache poisoning | REFUTED | No native unsafe deserialization/`eval`/`yaml`; canonical-JSON SHA-256, `allow_nan=False`, `run_id` re-checked. |
| 9 | Contract 4-point divergence (schema lacks hard rules; geometry sub-matrices + NaN) | **SURVIVES** (Low, integrity) | Exported schema enforces no cross-field rules; 3/4 validators skip geometry sub-matrices. V2-05. |
| 10 | CSV `__proto__` prototype pollution (`parseCsv`) | REFUTED | `Object.fromEntries` defines own props (no `__proto__` setter hit). |
| 11 | Secret/file leak via static server | REFUTED | `.dockerignore` excludes `.env*`/`source-data`/`tests`/`tools`/`audit`; explicit COPY list; upstream errors not echoed. |

## Round 2 — remaining surfaces (adapters, sdk params, EDF/zip/csv parsing)

| # | Candidate | Verdict | Killing/keeping argument |
|---|-----------|---------|--------------------------|
| 12 | `file_replay` O(n²) DFT + header-driven allocation | **SURVIVES** (Low, dev/CLI-only) | Genuine algorithmic DoS but no deployed endpoint reaches it. V2-04. |
| 13 | `build_params(**params)` arbitrary kwargs | REFUTED | Registered method params types use pydantic `model_validate`; plain-class path raises `TypeError` on unexpected kwargs; backend not in prod anyway. |
| 14 | `spikeinterface_adapter.run_sorter` arbitrary execution | REFUTED | No endpoint passes untrusted `sorter_name`; catalog registers only `band_power_summary`. No reachable sink. |
| 15 | ZIP decompression bomb (JSZip `loadAsync`) | REFUTED→Info | Client-side, user's own browser/own file → self-DoS only; not a server surface. |
| 16 | `findMember`/`findDataJson` zip-slip | REFUTED | In-memory only; nothing is written to disk from archive member names. |
| 17 | `sitecustomize.py` subprocess injection | REFUTED | Fixed argv (`[sys.executable,'-I','-c',_PREWARM_IMPORTS]`), no shell, repo-venv-gated, dev-only. |

## Round 3 — convergence check

No new candidate survived. Two consecutive rounds (2 and 3) yielded **no new survivor**
beyond those already logged → loop terminates (K=2 satisfied).

## Survivors carried to REPORT-v2.md

V2-01 (Med, prod), V2-02 (Low, prod), V2-03 (Low, dev), V2-04 (Low, dev), V2-05 (Low, integrity).
