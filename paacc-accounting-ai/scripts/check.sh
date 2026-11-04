#!/usr/bin/env bash
# Full regression gate: backend (SQLite; + PostgreSQL when PAACC_TEST_PG_URL is set), frontend types, tests, build.
# Exits non-zero on the first failure - run before every commit.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== backend tests ${PAACC_TEST_PG_URL:+(with PostgreSQL)}"
(cd backend && python -m pytest -q)
echo "== migrations in sync with models"
(cd backend && tmp="$(mktemp -d)" && PAACC_DATABASE_URL="sqlite:///$tmp/check.db" alembic upgrade head >/dev/null && \
  PAACC_DATABASE_URL="sqlite:///$tmp/check.db" alembic check && rm -rf "$tmp")
echo "== frontend"
(cd frontend && npx tsc --noEmit && npx vitest run && npm run build >/dev/null)
echo "ALL CHECKS PASSED"
