"""platform.audit_events: append-only (a database trigger rejects UPDATE and DELETE) and hash-chained per tenant."""
from __future__ import annotations

from typing import Any

from ifad_common.db import Base
from sqlalchemy import BigInteger, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_subject", "tenant_id", "subject_type", "subject_id"),
        Index("ix_audit_tenant_type", "tenant_id", "event_type"),
        {"schema": "platform"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    service: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[str] = mapped_column(String(40), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    __mapper_args__ = {"eager_defaults": False}


AUDIT_SUMMARY_FIELDS: tuple[str, ...] = ("id", "tenant_id", "event_type", "actor", "actor_kind", "actor_roles", "service",
                                         "subject_type", "subject_id", "run_id", "correlation_id", "details", "occurred_at",
                                         "prev_hash", "hash")


def audit_to_dict(event: AuditEvent) -> dict[str, Any]:
    return {f: getattr(event, f) for f in AUDIT_SUMMARY_FIELDS}
