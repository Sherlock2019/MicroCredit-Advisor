#!/usr/bin/env bash
# Runs once when the PostgreSQL volume is first created (docker-entrypoint-initdb.d).
# Creates the schemas, the pgvector extension and one login role per service. Table-level grants are applied by the
# Alembic migration (database/migrations/versions/0001_initial.py) because the tables do not exist yet.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v gw="$SVC_GATEWAY_DB_PASSWORD" -v fin="$SVC_FINANCE_DB_PASSWORD" -v prj="$SVC_PROJECTS_DB_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS platform;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS projects;
CREATE ROLE svc_gateway LOGIN PASSWORD :'gw';
CREATE ROLE svc_finance LOGIN PASSWORD :'fin';
CREATE ROLE svc_projects LOGIN PASSWORD :'prj';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
