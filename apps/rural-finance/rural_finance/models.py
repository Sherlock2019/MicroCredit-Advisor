"""finance schema: loan applications, crop plans, cost lines and versioned analyses.

The borrower is pseudonymous. There are deliberately no columns for protected or sensitive personal attributes.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ifad_common.db import Base, TimestampMixin, new_id, utcnow
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

MONEY = Numeric(14, 2)


class LoanApplication(TimestampMixin, Base):
    __tablename__ = "loan_applications"
    __table_args__ = (Index("ix_loan_app_tenant_status", "tenant_id", "status"), {"schema": "finance"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reference: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    borrower_pseudonym: Mapped[str] = mapped_column(String(40), nullable=False)
    borrower_type: Mapped[str] = mapped_column(String(30), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    locality: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cultivated_area_ha: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    loan_purpose: Mapped[str] = mapped_column(String(300), nullable=False)
    requested_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    annual_interest_rate_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    repayment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    repayment_months: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    other_monthly_income: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    operating_expenses_monthly: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    existing_obligations_monthly: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    opening_cash_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    declared_annual_revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    declared_production_costs: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)

    crops: Mapped[list[CropPlanRow]] = relationship(back_populates="application", cascade="all, delete-orphan",
                                                    order_by="CropPlanRow.harvest_month")
    costs: Mapped[list[CostLineRow]] = relationship(back_populates="application", cascade="all, delete-orphan",
                                                    order_by="CostLineRow.month")


class CropPlanRow(Base):
    __tablename__ = "crop_plans"
    __table_args__ = {"schema": "finance"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance.loan_applications.id", ondelete="CASCADE"), nullable=False)
    crop: Mapped[str] = mapped_column(String(60), nullable=False)
    area_ha: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    expected_yield_t_per_ha: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    yield_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    price_per_t: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    harvest_month: Mapped[int] = mapped_column(Integer, nullable=False)
    sale_share: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=1)
    application: Mapped[LoanApplication] = relationship(back_populates="crops")


class CostLineRow(Base):
    __tablename__ = "cost_lines"
    __table_args__ = {"schema": "finance"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance.loan_applications.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    application: Mapped[LoanApplication] = relationship(back_populates="costs")


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analysis_app_version", "application_id", "version", unique=True), {"schema": "finance"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance.loan_applications.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(40), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    scenarios: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    indicators: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_grounding: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    citations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    model_provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
