#!/usr/bin/env bash
# make e2e: start a throwaway Compose stack (project di1-e2e, its own volumes and ports, so a dev
# stack on the default ports is never touched), seed the catalogue roots, run the challenge
# example end to end (scripts/e2e_smoke.py), then remove the stack and its volumes.
# Ports: DI1_E2E_API_PORT (default 18000) and DI1_E2E_RABBITMQ_MANAGEMENT_PORT (25672).
# KEEP_E2E_STACK=1 leaves the stack running for inspection.
set -euo pipefail

cd "$(dirname "$0")/.."
export DI1_API_PORT="${DI1_E2E_API_PORT:-18000}"
export DI1_RABBITMQ_MANAGEMENT_PORT="${DI1_E2E_RABBITMQ_MANAGEMENT_PORT:-25672}"
compose=(docker compose -p di1-e2e)

cleanup() {
  if [[ "${KEEP_E2E_STACK:-0}" == "1" ]]; then
    echo "e2e: stack di1-e2e left running (KEEP_E2E_STACK=1); remove it with: docker compose -p di1-e2e down -v"
  else
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"${compose[@]}" up -d --build --wait
"${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -q \
  -U "${DI1_DB_USER:-di1}" -d "${DI1_DB_NAME:-di1}" < scripts/seed_catalogue.sql
python3 scripts/e2e_smoke.py --api "http://127.0.0.1:${DI1_API_PORT}"
