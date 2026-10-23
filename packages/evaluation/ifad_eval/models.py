"""platform.evaluation_runs: one row per evaluation execution (dataset version, provider, metrics, decision)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ifad_common.db import Base, new_id, utcnow
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = {"schema": "platform"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    suite: Mapped[str] = mapped_column(String(60), nullable=False)  # rag_retrieval | finance_rules | delay_model ...
    dataset_version: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(60), nullable=False)
    code_version: Mapped[str] = mapped_column(String(80), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    release_decision: Mapped[str] = mapped_column(String(40), nullable=False)
    failures: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
