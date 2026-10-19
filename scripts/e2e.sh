#!/usr/bin/env bash
# make e2e: start a throwaway Compose stack (its own project, volumes, images and ports, so a dev
# stack on the default ports is never touched), whose `seed` service seeds the catalogue and the
# DI1 product; apply the seed again (`make seed`'s step, which must change nothing), run the
# challenge example end to end (scripts/e2e_smoke.py), then remove the stack and its volumes.
# It also checks that the web container serves the UI and forwards the API.
# Several checkouts (git worktrees) may run it at the same time without colliding:
# - project: di1-e2e-<hash of the checkout's path> by default; DI1_E2E_PROJECT overrides it.
# - images: the built images are tagged with the project instead of :local, so one run never
#   starts the code another checkout built; cleanup removes those tags.
# - ports: free host ports picked at start (printed); DI1_E2E_API_PORT, DI1_E2E_WEB_PORT and
#   DI1_E2E_RABBITMQ_MANAGEMENT_PORT override them.
# KEEP_E2E_STACK=1 leaves the stack running for inspection.
set -euo pipefail

cd "$(dirname "$0")/.."
# Three distinct free ports on 127.0.0.1 (where compose.yaml publishes). They are free when picked,
# not reserved: something may take one before `up` binds it, and `up` then fails loudly ("port is
# already allocated"); run again, or set the DI1_E2E_*_PORT variables.
read -r free_api free_web free_rabbitmq < <(python3 -c '
import socket
socks = [socket.socket() for _ in range(3)]
for s in socks:
    s.bind(("127.0.0.1", 0))
print(*(s.getsockname()[1] for s in socks))
')
export DI1_API_PORT="${DI1_E2E_API_PORT:-$free_api}"
export DI1_WEB_PORT="${DI1_E2E_WEB_PORT:-$free_web}"
export DI1_RABBITMQ_MANAGEMENT_PORT="${DI1_E2E_RABBITMQ_MANAGEMENT_PORT:-$free_rabbitmq}"
# The challenge checks need an empty ledger: the demo service skips its data.
export DI1_DEMO=0
# Compose project names allow only lowercase letters, digits, - and _; the hash is hex.
project="${DI1_E2E_PROJECT:-di1-e2e-$(python3 -c '
import hashlib, os
print(hashlib.sha256(os.getcwd().encode()).hexdigest()[:8])
')}"
compose=(docker compose -p "$project")
echo "e2e: project ${project}; API on :${DI1_API_PORT}, web on :${DI1_WEB_PORT}," \
  "RabbitMQ management on :${DI1_RABBITMQ_MANAGEMENT_PORT}"
remove_hint="docker compose -p ${project} down -v; docker image rm di1-backend:${project} di1-web:${project}"

# A stack left by KEEP_E2E_STACK=1, an interrupted run, or a `down` without -v (its volumes) would
# carry its data into this run: refuse instead of reusing it, and leave it untouched. Volumes are
# matched by label and by name (<project>_…), since an unlabelled one would be reused too.
if [[ -n "$("${compose[@]}" ps -aq)" ||
      -n "$(docker volume ls -q --filter "label=com.docker.compose.project=${project}")" ||
      -n "$(docker volume ls -q --filter "name=^${project}_")" ]]; then
  echo "e2e: project ${project} already exists; remove it with: docker compose -p ${project} down -v" \
    "(an unlabelled ${project}_* volume needs docker volume rm)" >&2
  exit 1
fi

# Every built image (di1-backend:local, di1-web:local) gets this project's tag instead, through an
# override file, so a parallel run in another checkout cannot retag the image this one starts.
# Both calls read compose.yaml alone, so the retagged services are the ones started.
override="$(mktemp "${TMPDIR:-/tmp}/di1-e2e-override.XXXXXX")"
trap 'rm -f "$override"' EXIT
docker compose -f compose.yaml config --format json | python3 -c '
import json, sys
project = sys.argv[1]
services = json.load(sys.stdin)["services"]
print(json.dumps({"services": {
    name: {"image": svc["image"].rsplit(":", 1)[0] + ":" + project}
    for name, svc in services.items() if "build" in svc
}}))
' "$project" > "$override"
compose+=(-f compose.yaml -f "$override")

cleanup() {
  local status=$?
  if [[ "${KEEP_E2E_STACK:-0}" == "1" ]]; then
    # The override stays: a later `docker compose -p ... -f compose.yaml -f <it>` keeps these images.
    echo "e2e: stack ${project} left running (KEEP_E2E_STACK=1; override ${override});" \
      "remove it with: ${remove_hint}"
    exit "$status"
  elif ! "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1; then
    echo "e2e: could not remove stack ${project}; remove it with: ${remove_hint}" >&2
    # Keep the smoke's own failure status; a passing smoke still fails when cleanup fails.
    [[ $status -eq 0 ]] && status=1
  else
    # Untag this project's images by name (an id could also carry another checkout's tag); the
    # build cache stays.
    docker image ls --format '{{.Repository}}:{{.Tag}}' --filter "reference=*:${project}" |
      xargs docker image rm >/dev/null 2>&1 || true
  fi
  rm -f "$override"
  exit "$status"
}
trap cleanup EXIT

"${compose[@]}" up -d --build --wait
# The container's own user and database: Compose may have taken them from a .env this shell
# never read.
"${compose[@]}" exec -T postgres sh -c \
  'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < scripts/seed_catalogue.sql
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
