"""Builds engine inputs from the synthetic dataset so tests and the demo use the same fixtures."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from rural_finance.schemas import ApplicationCreate
from rural_finance.services.cashflow import CostLine, CropPlan, FarmCashFlowInput, LoanTerms

DATA = Path(__file__).resolve().parents[1] / "database" / "synthetic-data"


def finance_case(key: str) -> dict:
    spec = json.loads((DATA / "finance_applications.json").read_text(encoding="utf-8"))
    return next(a for a in spec["applications"] if a["key"] == key)


def engine_input(key: str, **loan_overrides) -> FarmCashFlowInput:
    p = ApplicationCreate.model_validate(finance_case(key)["payload"])
    loan = dict(amount=p.requested_amount, annual_rate_pct=p.annual_interest_rate_pct, term_months=p.term_months,
                repayment_type=p.repayment_type, repayment_months=tuple(p.repayment_months))
    loan.update(loan_overrides)
    return FarmCashFlowInput(
        currency=p.currency, start_month=p.start_month,
        crops=tuple(CropPlan(c.crop, c.area_ha, c.expected_yield_t_per_ha, c.price_per_t, c.harvest_month, c.sale_share, c.yield_basis)
                    for c in p.crops),
        costs=tuple(CostLine(c.category, c.amount, c.month, c.kind) for c in p.costs),
        loan=LoanTerms(**loan), other_monthly_income=p.other_monthly_income,
        operating_expenses_monthly=p.operating_expenses_monthly, existing_obligations_monthly=p.existing_obligations_monthly,
        opening_cash_balance=p.opening_cash_balance,
    )


def simple_input(**kw) -> FarmCashFlowInput:
    base = dict(currency="USD", start_month=date(2026, 1, 1),
                crops=(CropPlan("maize", Decimal("1"), Decimal("3"), Decimal("300"), 6),),
                costs=(CostLine("inputs", Decimal("400"), 1),),
                loan=LoanTerms(Decimal("600"), Decimal("12"), 6, "bullet"))
    base.update(kw)
    return FarmCashFlowInput(**base)
