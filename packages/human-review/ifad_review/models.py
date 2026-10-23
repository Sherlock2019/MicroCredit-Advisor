"""platform.review_decisions: append-only record of every workflow transition (who, when, why, on what evidence)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ifad_common.db import Base, new_id, utcnow
from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (Index("ix_review_subject", "tenant_id", "subject_type", "subject_id"), {"schema": "platform"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_state: Mapped[str] = mapped_column(String(30), nullable=False)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    versions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # policy/rule/model versions
    audit_event_id: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def decision_to_dict(d: ReviewDecision) -> dict[str, Any]:
    return {"id": str(d.id), "workflow": d.workflow, "from_state": d.from_state, "to_state": d.to_state,
            "actor": d.actor, "actor_kind": d.actor_kind, "actor_roles": d.actor_roles, "reason": d.reason,
            "evidence_refs": d.evidence_refs, "versions": d.versions, "audit_event_id": d.audit_event_id,
            "decided_at": d.decided_at.isoformat()}
