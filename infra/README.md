# Infrastructure

Deployment and infrastructure configuration live here.

## Topology

Two services are defined in `docker-compose.yml`:

- `static` — Node server from existing `server.mjs` (static frontend on `8080`).
- `backend` — FastAPI app from `packages/backend` served by Uvicorn on `8000`.

Both services attach to the shared `neuromouse` compose network.

## Runtime scopes

- 🅱 (workbench+demo)
  - Static scope: `docker compose --profile workbench up --build` (starts only `static`).
  - Backend dev scope: `docker compose --profile backend-dev up --build backend` (starts only `backend`).
- 🅰 (hosted)
  - Hosted scope: `docker compose --profile hosted up --build` (starts both `static` and `backend`).

## Backend environment

Set these variables on the Railway service named `speedmouse` (the Node static service that exposes `/api/explain`):

- `EXPLAIN_TOKEN` — required by explain endpoint in server integration path.
- `ANTHROPIC_API_KEY` — required API key for Claude.
- `EXPLAIN_API_URL` — explain upstream URL override (optional, defaults to `https://api.anthropic.com/v1/messages`).
- `EXPLAIN_RATE_LIMIT_PER_MIN` — per-minute request budget (optional).
- `EXPLAIN_CORS_ALLOW_ORIGINS` — comma-separated allowed browser origins (optional, if your UI is cross-origin).
- `NEUROMOUSE_BACKEND_DB` — backend sqlite path (container default: `/data/neuromouse_backend.sqlite3`).
- `PORT` / `BACKEND_PORT` — backend listen port for Uvicorn.
- `BACKEND_SCOPE` — profile signal for internal behavior/debugging.

For local smoke verification, keep tokens blank unless you intentionally call explain endpoints.

### How to enable `/api/explain`

- Keep `speedmouse` deployed with `EXPLAIN_TOKEN` and `ANTHROPIC_API_KEY` set.
- Leave `EXPLAIN_API_URL` unset (default official host) unless you have a private proxy and set `EXPLAIN_ALLOW_THIRD_PARTY_API=1`.
- The frontend must send the explain token in the request header:

```
X-Explain-Token: <EXPLAIN_TOKEN>
```

Current repository UI (`js/viewer.js`) calls `/api/explain` directly without this header, so this is an outward deployment integration step.

## Static image shape

`.dockerignore` excludes Python/tooling/build cache artifacts to keep `Dockerfile` build context trim for the static image.

## Required verification commands

When Docker is available:

1. Validate composition:

```bash
docker compose -f docker-compose.yml config
```

2. Build both services:

```bash
docker compose --profile hosted build
```

3. Start both services:

```bash
docker compose --profile hosted up -d --build
```

4. Smoke checks:

```bash
curl -sS http://127.0.0.1:8080/index.html
curl -sS http://127.0.0.1:8000/sessions
curl -sS http://127.0.0.1:8000/methods
```

5. Stop:

```bash
docker compose --profile hosted down
```

If Docker is not available in this executor, run `docker-compose -f docker-compose.yml config` to validate structure and keep the exact commands above for execution in an environment with Docker running.
