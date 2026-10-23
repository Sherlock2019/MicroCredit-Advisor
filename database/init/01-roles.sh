#!/usr/bin/env bash
# Runs once when the PostgreSQL volume is first created. Creates schemas, pgvector and one role per service.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS platform;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS projects;
CREATE ROLE svc_gateway LOGIN;
CREATE ROLE svc_finance LOGIN;
CREATE ROLE svc_projects LOGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
