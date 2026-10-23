"""projects schema: registry, membership, sites (map), milestones, budget, expenditures, indicators, reports, briefs."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ifad_common.db import Base, TimestampMixin, new_id, utcnow
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

MONEY = Numeric(16, 2)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_tenant_country", "tenant_id", "country"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    programme_name: Mapped[str] = mapped_column(String(200), nullable=False)
    theme: Mapped[str] = mapped_column(String(60), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    objectives: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expected_results: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    baseline_summary: Mapped[str | None] = mapped_column(Text)
    implementing_organization: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reporting_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    financing_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)

    sites: Mapped[list[ProjectSite]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "subject", name="uq_member_project_subject"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    project_role: Mapped[str] = mapped_column(String(40), nullable=False)
    added_by: Mapped[str] = mapped_column(String(200), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProjectSite(Base):
    __tablename__ = "project_sites"
    __table_args__ = (Index("ix_sites_geo", "country", "region", "city"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    site_name: Mapped[str] = mapped_column(String(160), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    beneficiaries_target: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    beneficiaries_reached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    site_status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    project: Mapped[Project] = relationship(back_populates="sites")


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("project_id", "activity_code", name="uq_milestone_code"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    activity_code: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    component: Mapped[str] = mapped_column(String(120), nullable=False)
    planned_start: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end: Mapped[date] = mapped_column(Date, nullable=False)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_end: Mapped[date | None] = mapped_column(Date)
    planned_progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    actual_progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    responsible_unit: Mapped[str] = mapped_column(String(120), nullable=False)
    evidence_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform.documents.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # not_started | in_progress | completed | cancelled
    reviewer_comments: Mapped[str | None] = mapped_column(Text)


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    __table_args__ = (UniqueConstraint("project_id", "component", name="uq_budget_component"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    component: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    budget_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    committed_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # contracts signed, not yet necessarily paid
    actual_expenditure: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # cumulative disbursed/spent
    reporting_period_end: Mapped[date] = mapped_column(Date, nullable=False)


class Expenditure(Base):
    __tablename__ = "expenditures"
    __table_args__ = (UniqueConstraint("project_id", "component", "period_label", name="uq_expenditure_period"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    component: Mapped[str] = mapped_column(String(120), nullable=False)
    period_label: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. 2025-Q3
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class Indicator(Base):
    __tablename__ = "indicators"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_indicator_code"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)  # output | outcome | impact
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_value: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    target_value: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reported_actual: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    reporting_period: Mapped[str | None] = mapped_column(String(20))
    data_source: Mapped[str | None] = mapped_column(String(200))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform.documents.id", ondelete="SET NULL"))
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False)  # unverified | partially_verified | verified | disputed
    quality_note: Mapped[str | None] = mapped_column(Text)


class FieldReport(Base):
    __tablename__ = "field_reports"
    __table_args__ = (UniqueConstraint("project_id", "report_type", "period_label", name="uq_report_period"), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    received_date: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform.documents.id", ondelete="SET NULL"))


class ProjectAnalysis(Base):
    __tablename__ = "project_analyses"
    __table_args__ = (Index("ix_project_analysis_version", "project_id", "version", unique=True), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProjectBrief(Base):
    __tablename__ = "project_briefs"
    __table_args__ = (Index("ix_brief_version", "project_id", "version", unique=True), {"schema": "projects"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.projects.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.project_analyses.id"), nullable=False)
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    grounding: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
