#!/usr/bin/env bash
# Backend test suite, identical locally and in CI (make test-backend).
#
# - TEST_DATABASE_URL set (CI: the postgres:16 service): that server is used.
# - TEST_DATABASE_URL unset: a throwaway postgres:16 container is started on a free local port
#   and removed on exit, whatever the outcome.
#
# REQUIRE_DATABASE_TESTS=1 always, so a database test can never be skipped silently. pytest's own
# exit code is kept: 5 (no tests collected) fails, unlike the pre-commit hook's fast subset.
set -euo pipefail
export LC_ALL=C.UTF-8
cd "$(dirname "$0")/../backend"
export REQUIRE_DATABASE_TESTS=1

container=""
scratch=""
# Both clean-up steps always run; the script's own failure wins, else a failed clean-up fails it.
cleanup() {
  local rc=$? failed=0
  set +e
  if [[ -n "$scratch" ]]; then
    uv run --frozen python ../scripts/scratch_database.py drop "$TEST_DATABASE_URL" "$scratch" \
      || failed=1
  fi
  if [[ -n "$container" ]]; then
    docker stop "$container" >/dev/null || failed=1
  fi
  if [[ $rc -ne 0 ]]; then
    exit "$rc"
  fi
  exit "$failed"
}
trap cleanup EXIT

if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  command -v docker >/dev/null 2>&1 || {
    echo "test-backend: TEST_DATABASE_URL is unset and docker is not available" >&2
    exit 1
  }
  name="di1-make-test-$$"
  docker run -d --rm --name "$name" -e POSTGRES_PASSWORD=x -p 127.0.0.1::5432 postgres:16 >/dev/null
  container=$name
  # TCP readiness: during initdb the entrypoint's temporary server listens on the socket only.
  ready=0
  for _ in $(seq 1 60); do
    if docker exec "$container" pg_isready -q -h 127.0.0.1 -U postgres; then
      ready=1
      break
    fi
    sleep 1
  done
  [[ $ready -eq 1 ]] || {
    echo "test-backend: postgres:16 not ready after 60 s" >&2
    exit 1
  }
  mapping=$(docker port "$container" 5432/tcp)
  port=${mapping##*:}
  export TEST_DATABASE_URL="postgresql+psycopg://postgres:x@127.0.0.1:${port}/postgres"
  echo "test-backend: throwaway postgres:16 '$container' on 127.0.0.1:${port}"
fi

# Plan §2: exactly one Alembic head.
heads=$(uv run --frozen alembic heads)
echo "alembic heads: ${heads}"
[[ $(wc -l <<<"$heads") -eq 1 && -n "$heads" ]] || {
  echo "test-backend: expected exactly one Alembic head" >&2
  exit 1
}

# Migration smoke: the CLI path (alembic upgrade head) on a fresh scratch database.
scratch_name="di1_smoke_$$"
scratch_url=$(uv run --frozen python ../scripts/scratch_database.py create "$TEST_DATABASE_URL" \
  "$scratch_name")
scratch=$scratch_name
DATABASE_URL="$scratch_url" uv run --frozen alembic upgrade head
current=$(DATABASE_URL="$scratch_url" uv run --frozen alembic current)
echo "alembic current after upgrade head: ${current}"
[[ "$current" == "$heads" ]] || {
  echo "test-backend: the scratch database is not at the head revision" >&2
  exit 1
}

uv run --frozen pytest --cov --cov-report=term-missing
