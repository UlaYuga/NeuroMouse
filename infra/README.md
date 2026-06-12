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

The backend container consumes these variables:

- `EXPLAIN_TOKEN` — required by explain endpoint in server integration path.
- `ANTHROPIC_API_KEY` — passed through to the explain upstream.
- `EXPLAIN_API_URL` — explain upstream URL (default: `https://api.anthropic.com/v1/messages`).
- `EXPLAIN_MODEL` — model name for explain responses.
- `EXPLAIN_RATE_LIMIT_PER_MIN` — per-minute request budget.
- `EXPLAIN_CORS_ALLOW_ORIGINS` — comma-separated allowed origins.
- `NEUROMOUSE_BACKEND_DB` — backend sqlite path (container default: `/data/neuromouse_backend.sqlite3`).
- `PORT` / `BACKEND_PORT` — backend listen port for Uvicorn.
- `BACKEND_SCOPE` — profile signal for internal behavior/debugging.

For local smoke verification, keep tokens blank unless you intentionally call explain endpoints.

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
