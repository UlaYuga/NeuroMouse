# Audit v2 — deployment-surface model

Severity in this audit is anchored to **what actually ships**, established from the repo.

## What the production image contains

`Dockerfile`:
```
FROM node:22-alpine
COPY package.json server.mjs ./
COPY index.html style.css ./
COPY data ./data
COPY js ./js
COPY assets ./assets
EXPOSE 8080
CMD ["node", "server.mjs"]
```

So the running process is **`server.mjs`** only. The Python packages
(`packages/backend`, `packages/core`, `packages/adapters`, `packages/sorting`,
`packages/sdk`, `contracts`) and `tools/` are **not copied** and are additionally
excluded by `.dockerignore` (`tests`, `tools`, `source-data`, `audit`, `.github`,
`.claude`, `node_modules`).

## Internet-facing routes (server.mjs)

| Route | Method | Notes |
|-------|--------|-------|
| `/healthz` | GET | returns `ok` |
| `/api/explain` | POST | LLM proxy → **V2-01** |
| `/*` | GET | static file server, root-jailed via `startsWith(root)` |

There is **no** `/sessions`, `/methods`, `/jobs`, `/ws/*` route in production — those
exist only in the FastAPI app, which is not deployed.

## Frontend ↔ backend wiring

`js/backend-client.js` defaults `baseUrl = ""` → same-origin. Against `server.mjs`,
backend-mode endpoints 404, so the viewer falls back to the bundled static
`data/data.json`. The "backend live method run" path is therefore a local-dev feature.

## Consequence for severities

- Anything reachable only through the FastAPI app or the Python adapters/sorters is
  **dev/CLI-only** (V2-03, V2-04, parts of V2-05) — real bugs, but not exposed.
- The only findings that touch an internet-facing surface are **V2-01** and **V2-02**,
  both in `server.mjs` / the static bundle.
- The ZIP/CSV import path runs **client-side in the user's own browser on their own
  files**, so import-parsing weaknesses are self-DoS, not server compromise.

If the FastAPI backend is ever containerized and exposed, re-rate V2-03 (and the WS
CSWSH / NaN-ingestion items) upward accordingly.
