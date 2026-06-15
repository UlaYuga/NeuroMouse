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

Set these variables on the Railway service named `backend` (the FastAPI service):

- `DATABASE_URL` — Railway Postgres reference variable, usually `${{ Postgres.DATABASE_URL }}`.
- `NEUROMOUSE_MAX_BODY_BYTES` — maximum raw HTTP request body size before parsing
  (optional, default `10485760`; `0` disables). Oversized dataset/method upload requests return
  `413`.
- `NEUROMOUSE_MAX_DATASET_BYTES` — maximum decoded dataset payload size for `/sessions`
  (optional, default `33554432`).
- `NEUROMOUSE_LOG_LEVEL` — Python log threshold for backend JSON request logs (optional, default
  `INFO`). Logs are emitted as one JSON object per line on stderr; attach any Railway/team log sink
  to container logs rather than adding an in-process APM dependency.

For local smoke verification, keep tokens blank unless you intentionally call explain endpoints.

### How to enable `/api/explain`

- Keep `speedmouse` deployed with `EXPLAIN_TOKEN` and `ANTHROPIC_API_KEY` set.
- Leave `EXPLAIN_API_URL` unset (default official host) unless you have a private proxy and set `EXPLAIN_ALLOW_THIRD_PARTY_API=1`.
- The frontend must send the explain token in the request header:

```
X-Explain-Token: <EXPLAIN_TOKEN>
```

Current repository UI (`js/viewer.js`) calls `/api/explain` directly without this header, so this is an outward deployment integration step.

## Railway Postgres backups

Railway's PostgreSQL template stores data on a Railway volume. Railway's native volume Backups
feature covers database volumes and can create manual backups or scheduled Daily / Weekly /
Monthly backups from the service settings panel.

For production:

1. Open the Railway project canvas.
2. Select the PostgreSQL service.
3. Open the service settings panel, then the **Backups** tab.
4. Enable at least a Daily schedule before exposing user uploads. Railway currently retains Daily
   backups for 6 days, Weekly backups for 1 month, and Monthly backups for 3 months.
5. Trigger a manual backup after any risky migration or before a restore drill.
6. To restore, choose a backup in the same **Backups** tab. Railway stages the restored volume;
   review the staged change in project canvas **Details**, then deploy it.

Sources: Railway PostgreSQL docs (`https://docs.railway.com/databases/postgresql`) and Railway
Backups docs (`https://docs.railway.com/volumes/backups`).

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
