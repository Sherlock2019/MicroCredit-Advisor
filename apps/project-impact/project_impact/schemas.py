from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SiteIn(Strict):
    site_name: str = Field(min_length=2, max_length=160)
    country: str = Field(min_length=2, max_length=80)
    region: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    activity_type: str = Field(min_length=2, max_length=80)
    beneficiaries_target: int = Field(0, ge=0)
    beneficiaries_reached: int = Field(0, ge=0)


class ProjectCreate(Strict):
    code: str = Field(pattern=r"^[A-Z0-9-]{4,30}$")
    name: str = Field(min_length=3, max_length=200)
    programme_name: str = Field(min_length=3, max_length=200)
    theme: Literal["irrigation", "market_access", "cooperatives", "value_chain", "climate_resilience", "rural_finance", "livelihoods"]
    country: str = Field(min_length=2, max_length=80)
    objectives: list[str] = Field(min_length=1, max_length=10)
    expected_results: list[str] = Field(default_factory=list, max_length=20)
    baseline_summary: str | None = Field(None, max_length=4000)
    implementing_organization: str = Field(min_length=3, max_length=200)
    start_date: date
    end_date: date
    reporting_as_of: date
    financing_amount: Money = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    sites: list[SiteIn] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _dates(self) -> ProjectCreate:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if not self.start_date <= self.reporting_as_of <= self.end_date:
            raise ValueError("reporting_as_of must fall within the project period")
        return self


class ProjectSummary(BaseModel):
    id: str
    code: str
    name: str
    theme: str
    country: str
    financing_amount: Decimal
    currency: str
    status: str
    start_date: date
    end_date: date
    reporting_as_of: date
    synthetic: bool
    site_count: int
    updated_at: datetime


class AskRequest(Strict):
    question: str = Field(min_length=3, max_length=500)


class BriefReviewRequest(Strict):
    brief_id: str
    action: Literal["submit", "request_changes", "approve"]
    reason: str | None = Field(None, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


BRIEF_ACTION_TO_STATE = {"submit": "SUBMITTED", "request_changes": "CHANGES_REQUESTED", "approve": "APPROVED"}
