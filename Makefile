# MicroCredit Advisor POC — developer shortcuts (Linux / WSL / macOS). To just run the demo: ./start.sh
SHELL := /bin/bash
PY := .venv/bin/python
ENV_LOAD := set -a; [ -f .env ] && source .env; set +a
OWNER_URL = postgresql+psycopg://ifad_owner@localhost:$${POSTGRES_HOST_PORT:-55433}/ifad_platform
export PYTHONPATH := packages/common:packages/audit:packages/document-ingestion:packages/rag:packages/model-gateway:packages/evaluation:packages/human-review:integrations/creditpappraisal-adapter:integrations/supplychain-adapter:apps/api-gateway:apps/rural-finance:apps/project-impact:.

.PHONY: help up down venv db-up migrate seed db-reset test test-unit lint smoke

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-10s %s\n", $$1, $$2}'

up: ## start the whole demo (same as ./start.sh)
	./start.sh

down: ## stop the demo
	./start.sh stop

venv: ## create .venv for tests and local development
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e ".[dev]"

db-up: ## start only PostgreSQL/pgvector (for tests)
	docker compose up -d postgres

migrate: ## apply migrations to the dev database
	$(ENV_LOAD); DATABASE_URL="$(OWNER_URL)" .venv/bin/alembic -c database/alembic.ini upgrade head

seed: ## load the synthetic demo data into the dev database
	$(ENV_LOAD); DATABASE_URL="$(OWNER_URL)" STORAGE_LOCAL_ROOT=./data/object-store $(PY) scripts/seed_demo.py

db-reset: ## DESTRUCTIVE (local only): drop the demo schemas, re-migrate and re-seed
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U ifad_owner -d ifad_platform \
	  -c "DROP SCHEMA IF EXISTS platform, finance, projects CASCADE" -c "DROP TABLE IF EXISTS public.alembic_version" \
	  -c "CREATE SCHEMA platform" -c "CREATE SCHEMA finance" -c "CREATE SCHEMA projects"
	rm -rf data/object-store
	$(MAKE) migrate seed

test: ## all tests (uses a separate ifad_platform_test database)
	$(ENV_LOAD); DATABASE_URL="$(OWNER_URL)" $(PY) -m pytest tests -p no:warnings

test-unit: ## unit tests only (no database)
	$(PY) -m pytest tests/unit

lint:
	.venv/bin/ruff check .

smoke: ## check a running stack end to end through the portal
	python3 scripts/smoke_test.py
