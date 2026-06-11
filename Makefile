.PHONY: test lint fuzz dev

test:
	uv run pytest && node --test tests/*.test.mjs

lint:
	uv run ruff check && uv run ty check

fuzz:
	(cd tests/property && node --test validate-data.property.test.mjs) && \
	(cd tests/property && node --test import-csv-zip.property.test.mjs) && \
	(cd tests/fuzz && npm run fuzz:deep)

dev:
	uv run uvicorn neuromouse_backend.app:app --app-dir packages/backend/src --reload --host 127.0.0.1 --port 8000 & \
	npm start
