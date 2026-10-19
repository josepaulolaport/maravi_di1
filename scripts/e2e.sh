#!/usr/bin/env bash
# make e2e: start a throwaway Compose stack (project di1-e2e, its own volumes and ports, so a dev
# stack on the default ports is never touched), seed the catalogue roots, run the challenge
# example end to end (scripts/e2e_smoke.py), then remove the stack and its volumes.
# It also checks that the web container serves the UI and forwards the API.
# Ports: DI1_E2E_API_PORT (default 18000), DI1_E2E_WEB_PORT (18080) and
# DI1_E2E_RABBITMQ_MANAGEMENT_PORT (25672).
# KEEP_E2E_STACK=1 leaves the stack running for inspection.
set -euo pipefail

cd "$(dirname "$0")/.."
export DI1_API_PORT="${DI1_E2E_API_PORT:-18000}"
export DI1_WEB_PORT="${DI1_E2E_WEB_PORT:-18080}"
export DI1_RABBITMQ_MANAGEMENT_PORT="${DI1_E2E_RABBITMQ_MANAGEMENT_PORT:-25672}"
project=di1-e2e
compose=(docker compose -p "$project")

# A stack left by KEEP_E2E_STACK=1, an interrupted run, or a `down` without -v (its volumes) would
# carry its data into this run: refuse instead of reusing it, and leave it untouched.
if [[ -n "$("${compose[@]}" ps -aq)" ||
      -n "$(docker volume ls -q --filter "label=com.docker.compose.project=${project}")" ]]; then
  echo "e2e: project ${project} already exists; remove it with: docker compose -p ${project} down -v" >&2
  exit 1
fi

cleanup() {
  local status=$?
  if [[ "${KEEP_E2E_STACK:-0}" == "1" ]]; then
    echo "e2e: stack ${project} left running (KEEP_E2E_STACK=1); remove it with: docker compose -p ${project} down -v"
  elif ! "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1; then
    echo "e2e: could not remove stack ${project}; remove it with: docker compose -p ${project} down -v" >&2
    # Keep the smoke's own failure status; a passing smoke still fails when cleanup fails.
    [[ $status -eq 0 ]] && status=1
  fi
  exit "$status"
}
trap cleanup EXIT

"${compose[@]}" up -d --build --wait
"${compose[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -q \
  -U "${DI1_DB_USER:-di1}" -d "${DI1_DB_NAME:-di1}" < scripts/seed_catalogue.sql
python3 scripts/e2e_smoke.py --api "http://127.0.0.1:${DI1_API_PORT}"

# The web service: the SPA on / (and on a client-side route) and the API through its proxy.
web="http://127.0.0.1:${DI1_WEB_PORT}"
for path in / /carteira; do
  page="$(curl -fsS "${web}${path}")"
  [[ "$page" == *'<div id="root">'* ]] ||
    { echo "e2e: web ${path} did not serve the app" >&2; exit 1; }
done
curl -fsS -o /dev/null "${web}/api/instrument-types" ||
  { echo "e2e: web did not forward /api/instrument-types" >&2; exit 1; }
echo "e2e: web serves the UI and forwards the API on ${web}"
