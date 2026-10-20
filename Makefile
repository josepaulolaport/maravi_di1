# One-command setup and checks. CI (.github/workflows/ci.yml) calls these same targets.
#
#   make install   backend dependencies (uv sync --frozen) and frontend dependencies (npm ci)
#   make lint      uv lock --check, ruff check and ruff format --check (backend/, scripts/), mypy
#                  (backend/ and every scripts/*.py), frontend eslint, tsc and prettier --check
#   make test      Alembic head and migration smoke, then pytest with coverage against PostgreSQL 16
#                  (a throwaway container unless TEST_DATABASE_URL is set), then the frontend tests
#   make seed      catalogue (FUTURE, INTEREST_RATE_FUTURE, the DI1 product) into the running stack, again
#   make e2e       the challenge example end to end on a throwaway Compose stack (scripts/e2e.sh)
#
# Every recipe fails on the first failing command; nothing is silenced. Recipes avoid pipes:
# macOS ships GNU Make 3.81, which ignores .SHELLFLAGS, so pipefail lives in the scripts.

SHELL := bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

.PHONY: help install install-backend install-frontend lint lint-backend lint-frontend \
	test test-backend test-frontend lint-commits seed e2e

help:
	@echo "make install | make lint | make test | make seed | make e2e"
	@echo "split: {install,lint,test}-{backend,frontend}; make lint-commits [BASE=origin/main] [HEAD_REF=HEAD]"

install: install-backend install-frontend

install-backend:
	cd backend && uv sync --frozen

install-frontend:
	cd frontend && npm ci

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv lock --check
	cd backend && uv run --frozen ruff check . ../scripts
	cd backend && uv run --frozen ruff format --check . ../scripts
	cd backend && uv run --frozen mypy src tests migrations ../scripts

lint-frontend:
	cd frontend && npm run lint && npm run typecheck && npm run format:check

test: test-backend test-frontend

test-backend:
	scripts/test-backend.sh

test-frontend:
	cd frontend && npm test

BASE ?= origin/main
HEAD_REF ?= HEAD
lint-commits:
	scripts/lint-commits.sh "$(BASE)" "$(HEAD_REF)"

seed:
	docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < scripts/seed_catalogue.sql

e2e:
	scripts/e2e.sh
