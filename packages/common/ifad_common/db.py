"""SQLAlchemy 2 engine, declarative base and the request-scoped session dependency."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import DateTime, MetaData, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ifad_common.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_size=settings.db_pool_size, pool_pre_ping=True, future=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def new_session() -> Session:
    return _session_factory()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request; commit on success, roll back on any error."""
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_ready() -> tuple[bool, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            has_vector = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
            revision = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
        if not has_vector:
            return False, "pgvector extension missing"
        return True, f"migrations at {revision}"
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        return False, type(exc).__name__
