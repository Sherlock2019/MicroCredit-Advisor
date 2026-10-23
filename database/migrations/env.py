"""Alembic environment. Uses MIGRATION_DATABASE_URL (owner role) or DATABASE_URL."""
from __future__ import annotations

import os

import ifad_audit.models  # noqa: F401
import ifad_eval.models  # noqa: F401
import ifad_rag.models  # noqa: F401
import ifad_review.models  # noqa: F401
import project_impact.models  # noqa: F401
import rural_finance.models  # noqa: F401
from alembic import context
from ifad_common.config import get_settings
from ifad_common.db import Base
from sqlalchemy import create_engine, pool

target_metadata = Base.metadata
SCHEMAS = {"platform", "finance", "projects"}


def _url() -> str:
    return os.environ.get("MIGRATION_DATABASE_URL") or get_settings().database_url


# Created by hand in migrations (expression/partial index the models cannot describe).
MANUAL_OBJECTS = {"ix_chunks_embedding_hnsw_384"}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return name not in MANUAL_OBJECTS


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, include_schemas=True,
                      include_name=include_name, version_table_schema="public")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True,
                          include_name=include_name, version_table_schema="public", compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
