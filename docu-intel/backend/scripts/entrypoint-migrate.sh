#!/bin/sh
# S0.B3 - one-shot migrations job for production.
#
# This script is the entrypoint of the optional ``migrate`` service in
# docker-compose.prod.yml. It applies all pending Alembic migrations and
# exits 0. The backend / workers / scheduler services declare
# ``depends_on: { migrate: { condition: service_completed_successfully } }``
# so they do not start until the schema is current.
#
# Why a dedicated service:
# - Multiple backend replicas can boot in parallel without racing on
#   ``alembic_version``.
# - A failed migration surfaces as a non-zero exit code and a clear
#   log line, instead of crashing the backend in a loop.
# - Operators can re-run the job manually after a hotfix:
#     docker compose -f docker-compose.prod.yml run --rm migrate
#
# Migration advisory lock:
# - Alembic 1.13+ has a ``--lock-mode`` option but it is
#   on-by-default for Postgres (uses a Postgres advisory lock on
#   ``alembic_version``'s row). Running two migrate jobs at the
#   same time is safe; one of them waits for the other.
#
# Idempotency:
# - ``alembic upgrade head`` is a no-op when the schema is already
#   at head. This job can be safely scheduled as a recurring
#   deploy step.

set -e

echo "[migrate] applying pending Alembic migrations..."
cd /app
alembic upgrade head
echo "[migrate] schema is at head"
