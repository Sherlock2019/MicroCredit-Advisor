"""platform.documents and platform.document_chunks (pgvector). Shared by both business applications."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from ifad_common.db import Base, new_id, utcnow
from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

DOMAINS = ("finance", "project", "reference")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "domain", "scope_id", "sha256", name="uq_documents_scope_sha"),
        Index("ix_documents_scope", "tenant_id", "domain", "scope_id"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")  # synthetic | uploaded | public_reference
    source_url: Mapped[str | None] = mapped_column(String(500))
    publication_date: Mapped[date | None] = mapped_column(Date)
    license: Mapped[str | None] = mapped_column(String(200))
    reporting_period: Mapped[str | None] = mapped_column(String(40))
    access_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str] = mapped_column(String(80), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_chunks_scope", "tenant_id", "domain", "scope_id", "embedding_model"),
        {"schema": "platform"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("platform.documents.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    reference: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(80), nullable=False)
    flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


def document_summary(doc: Document) -> dict[str, Any]:
    return {
        "id": str(doc.id), "title": doc.title, "filename": doc.filename, "document_type": doc.document_type,
        "domain": doc.domain, "scope_id": str(doc.scope_id) if doc.scope_id else None, "provenance": doc.provenance,
        "source_url": doc.source_url, "publication_date": doc.publication_date.isoformat() if doc.publication_date else None,
        "license": doc.license, "reporting_period": doc.reporting_period, "flags": doc.flags, "page_count": doc.page_count,
        "chunk_count": doc.chunk_count, "sha256": doc.sha256, "uploaded_by": doc.uploaded_by,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
