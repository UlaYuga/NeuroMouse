#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${NEUROMOUSE_SMOKE_URL:-http://127.0.0.1:4173}"
PLAYWRIGHT_NODE_PATH="$(
  npm exec --yes --package=@playwright/test@1.53.0 -- \
    node -p "process.env.PATH.split(':')[0].replace(/\\/\\.bin$/, '')"
)"

NEUROMOUSE_SMOKE_URL="$BASE_URL" \
NODE_PATH="$PLAYWRIGHT_NODE_PATH" \
npm exec --yes --package=@playwright/test@1.53.0 -- \
  playwright test tests/import-smoke.spec.cjs --reporter=line
