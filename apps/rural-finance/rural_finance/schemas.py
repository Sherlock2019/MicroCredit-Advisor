"""Typed request/response models. extra="forbid" everywhere: unknown fields (including any personal attribute such
as gender or age) are rejected rather than silently stored."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Status = Literal["DRAFT", "SUBMITTED", "ANALYZED", "IN_REVIEW", "NEEDS_INFORMATION", "APPROVED", "DECLINED"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CropPlanIn(Strict):
    crop: str = Field(min_length=2, max_length=60)
    area_ha: Decimal = Field(gt=0, le=100000, decimal_places=2)
    expected_yield_t_per_ha: Decimal = Field(ge=0, le=200, decimal_places=3)
    yield_basis: Literal["historical", "projected"] = "projected"
    price_per_t: Money
    harvest_month: int = Field(ge=1, le=72, description="Month index from the loan start month (1 = start month)")
    sale_share: Decimal = Field(Decimal("1"), ge=0, le=1, decimal_places=3)


class CostLineIn(Strict):
    category: str = Field(min_length=2, max_length=80)
    kind: Literal["production", "investment"] = "production"
    amount: Money
    month: int = Field(ge=1, le=60)


class ApplicationCreate(Strict):
    borrower_pseudonym: str = Field(pattern=r"^[A-Z]{2,4}-[A-Z0-9]{3,12}$", description="Pseudonymous id, never a name")
    borrower_type: Literal["smallholder_individual", "farmer_cooperative", "farmer_group"]
    group_name: str | None = Field(None, max_length=120, description="Fictional cooperative/group name")
    country: str = Field(min_length=2, max_length=80)
    region: str = Field(min_length=2, max_length=120)
    locality: str | None = Field(None, max_length=120)
    latitude: Decimal | None = Field(None, ge=-90, le=90)
    longitude: Decimal | None = Field(None, ge=-180, le=180)
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code")
    cultivated_area_ha: Decimal = Field(gt=0, le=100000)
    loan_purpose: str = Field(min_length=5, max_length=300)
    requested_amount: Money = Field(gt=0)
    annual_interest_rate_pct: Decimal = Field(ge=0, le=100, decimal_places=3)
    term_months: int = Field(ge=1, le=60)
    start_month: date = Field(description="First day of the loan's first month")
    repayment_type: Literal["seasonal_installments", "equal_monthly", "bullet"]
    repayment_months: list[int] = Field(default_factory=list, max_length=60)
    crops: list[CropPlanIn] = Field(min_length=1, max_length=20)
    costs: list[CostLineIn] = Field(default_factory=list, max_length=100)
    other_monthly_income: Money = Decimal("0")
    operating_expenses_monthly: Money = Decimal("0")
    existing_obligations_monthly: Money = Decimal("0")
    opening_cash_balance: Money = Decimal("0")
    declared_annual_revenue: Money | None = None
    declared_production_costs: Money | None = None

    @field_validator("start_month")
    @classmethod
    def _first_of_month(cls, v: date) -> date:
        return v.replace(day=1)

    @field_validator("borrower_pseudonym")
    @classmethod
    def _no_name_like(cls, v: str) -> str:
        if re.search(r"[a-z]", v):
            raise ValueError("pseudonym must be an opaque code")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> ApplicationCreate:
        if self.repayment_type == "seasonal_installments" and not self.repayment_months:
            raise ValueError("seasonal_installments requires repayment_months")
        if any(m < 1 or m > self.term_months for m in self.repayment_months):
            raise ValueError("repayment_months must be within the loan term")
        if any(c.month > self.term_months for c in self.costs):
            raise ValueError("cost months must be within the loan term")
        if sum((c.area_ha for c in self.crops), Decimal(0)) > self.cultivated_area_ha * 2:
            raise ValueError("crop areas exceed twice the cultivated area (two seasons maximum)")
        return self


class ApplicationSummary(BaseModel):
    id: str
    reference: str
    borrower_pseudonym: str
    borrower_type: str
    group_name: str | None
    country: str
    region: str
    locality: str | None
    currency: str
    requested_amount: Decimal
    status: Status
    synthetic: bool
    primary_crop: str | None
    created_by: str
    updated_at: datetime


class ApplicationOut(ApplicationSummary):
    cultivated_area_ha: Decimal
    loan_purpose: str
    annual_interest_rate_pct: Decimal
    term_months: int
    start_month: date
    repayment_type: str
    repayment_months: list[int]
    other_monthly_income: Decimal
    operating_expenses_monthly: Decimal
    existing_obligations_monthly: Decimal
    opening_cash_balance: Decimal
    declared_annual_revenue: Decimal | None
    declared_production_costs: Decimal | None
    latitude: Decimal | None
    longitude: Decimal | None
    crops: list[dict[str, Any]]
    costs: list[dict[str, Any]]
    allowed_transitions: list[str]
    documents: list[dict[str, Any]]
    latest_analysis_id: str | None


class ScenarioIn(Strict):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_ -]+$")
    yield_change_pct: Decimal = Field(Decimal("0"), ge=-100, le=200)
    price_change_pct: Decimal = Field(Decimal("0"), ge=-100, le=200)
    input_cost_change_pct: Decimal = Field(Decimal("0"), ge=-100, le=300)
    harvest_delay_months: int = Field(0, ge=0, le=12)


class SimulateRequest(Strict):
    scenarios: list[ScenarioIn] = Field(min_length=1, max_length=10)
    include_baseline: bool = True


class AnalyzeRequest(Strict):
    explain: bool = Field(True, description="Generate a source-cited explanation through the model gateway")


class AskRequest(Strict):
    question: str = Field(min_length=3, max_length=500)


class ReviewRequest(Strict):
    action: Literal["submit", "start_review", "request_information", "approve", "decline"]
    reason: str | None = Field(None, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


ACTION_TO_STATE = {"submit": "SUBMITTED", "start_review": "IN_REVIEW", "request_information": "NEEDS_INFORMATION",
                   "approve": "APPROVED", "decline": "DECLINED"}
