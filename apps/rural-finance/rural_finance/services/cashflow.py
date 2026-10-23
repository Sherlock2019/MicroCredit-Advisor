"""Agricultural seasonal cash-flow engine. Deterministic, Decimal-only, no LLM.

Conventions (also returned as `assumptions` with every result):
  * Money is Decimal in the application's ISO-4217 currency, rounded half-up to 0.01 per line item.
  * Month 1 is the loan start month; harvests, costs and repayments are placed on month indices 1..term.
  * Harvest revenue = area_ha x yield (t/ha) x price (per t) x share sold, received in the harvest month.
  * Interest: declining balance, accrued monthly at annual_rate / 12 on the outstanding principal. Accrued interest
    is paid with each instalment (seasonal / bullet) or inside the amortised payment (equal_monthly).
  * Loan proceeds are an inflow in the disbursement month (month 1).
  * Cash available for debt service = opening cash + loan proceeds + all inflows - all non-debt outflows over the term.
    Repayment coverage = cash available for debt service / new-loan debt service.
These are advisory indicators for a human credit officer. Nothing here approves or declines a loan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ENGINE_VERSION = "agri-cashflow/1.0.0"
CENT = Decimal("0.01")
ZERO = Decimal("0")


def q(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class CropPlan:
    crop: str
    area_ha: Decimal
    expected_yield_t_per_ha: Decimal
    price_per_t: Decimal
    harvest_month: int
    sale_share: Decimal = Decimal("1")
    yield_basis: str = "projected"


@dataclass(frozen=True)
class CostLine:
    category: str
    amount: Decimal
    month: int
    kind: str = "production"  # production | investment


@dataclass(frozen=True)
class LoanTerms:
    amount: Decimal
    annual_rate_pct: Decimal
    term_months: int
    repayment_type: str  # seasonal_installments | equal_monthly | bullet
    repayment_months: tuple[int, ...] = ()
    disbursement_month: int = 1


@dataclass(frozen=True)
class FarmCashFlowInput:
    currency: str
    start_month: date
    crops: tuple[CropPlan, ...]
    costs: tuple[CostLine, ...]
    loan: LoanTerms
    other_monthly_income: Decimal = ZERO
    operating_expenses_monthly: Decimal = ZERO
    existing_obligations_monthly: Decimal = ZERO
    opening_cash_balance: Decimal = ZERO


@dataclass(frozen=True)
class Scenario:
    name: str
    yield_change_pct: Decimal = ZERO
    price_change_pct: Decimal = ZERO
    input_cost_change_pct: Decimal = ZERO
    harvest_delay_months: int = 0

    @property
    def label(self) -> str:
        parts = []
        if self.yield_change_pct:
            parts.append(f"yield {self.yield_change_pct:+}%")
        if self.price_change_pct:
            parts.append(f"price {self.price_change_pct:+}%")
        if self.input_cost_change_pct:
            parts.append(f"input costs {self.input_cost_change_pct:+}%")
        if self.harvest_delay_months:
            parts.append(f"harvest {self.harvest_delay_months} month(s) late")
        return ", ".join(parts) or "baseline"


BASELINE = Scenario("baseline")
STANDARD_SCENARIOS: tuple[Scenario, ...] = (
    BASELINE,
    Scenario("yield_minus_20", yield_change_pct=Decimal("-20")),
    Scenario("price_minus_15", price_change_pct=Decimal("-15")),
    Scenario("yield_minus_20_and_price_minus_15", yield_change_pct=Decimal("-20"), price_change_pct=Decimal("-15")),
    Scenario("input_costs_plus_20", input_cost_change_pct=Decimal("20")),
    Scenario("harvest_delay_2_months", harvest_delay_months=2),
)


@dataclass
class MonthRow:
    month: int
    label: str
    opening_balance: Decimal
    harvest_revenue: Decimal
    other_income: Decimal
    loan_disbursement: Decimal
    production_costs: Decimal
    investment_costs: Decimal
    operating_expenses: Decimal
    existing_obligations: Decimal
    interest_paid: Decimal
    principal_paid: Decimal
    closing_balance: Decimal = ZERO

    @property
    def debt_service(self) -> Decimal:
        return self.interest_paid + self.principal_paid

    @property
    def cash_before_debt_service(self) -> Decimal:
        return (self.opening_balance + self.harvest_revenue + self.other_income + self.loan_disbursement
                - self.production_costs - self.investment_costs - self.operating_expenses - self.existing_obligations)

    def as_dict(self) -> dict:
        return {
            "month": self.month, "label": self.label, "opening_balance": self.opening_balance,
            "harvest_revenue": self.harvest_revenue, "other_income": self.other_income,
            "loan_disbursement": self.loan_disbursement, "production_costs": self.production_costs,
            "investment_costs": self.investment_costs, "operating_expenses": self.operating_expenses,
            "existing_obligations": self.existing_obligations, "interest_paid": self.interest_paid,
            "principal_paid": self.principal_paid, "debt_service": self.debt_service,
            "net_cash_flow": self.closing_balance - self.opening_balance, "closing_balance": self.closing_balance,
        }


@dataclass
class CashFlowResult:
    scenario: Scenario
    currency: str
    rows: list[MonthRow]
    summary: dict
    installments: list[dict]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"scenario": {"name": self.scenario.name, "label": self.scenario.label,
                             "yield_change_pct": self.scenario.yield_change_pct, "price_change_pct": self.scenario.price_change_pct,
                             "input_cost_change_pct": self.scenario.input_cost_change_pct,
                             "harvest_delay_months": self.scenario.harvest_delay_months},
                "currency": self.currency, "months": [r.as_dict() for r in self.rows], "summary": self.summary,
                "installments": self.installments, "warnings": self.warnings}


def month_label(start: date, index: int) -> str:
    months = start.year * 12 + (start.month - 1) + (index - 1)
    return f"{months // 12:04d}-{months % 12 + 1:02d}"


def _factor(pct: Decimal) -> Decimal:
    return Decimal("1") + pct / Decimal("100")


def harvest_revenue(crop: CropPlan, scenario: Scenario = BASELINE) -> Decimal:
    tonnes = crop.area_ha * crop.expected_yield_t_per_ha * _factor(scenario.yield_change_pct)
    return q(tonnes * crop.price_per_t * _factor(scenario.price_change_pct) * crop.sale_share)


def _principal_schedule(loan: LoanTerms) -> dict[int, Decimal]:
    if loan.amount <= 0:
        return {}
    if loan.repayment_type == "bullet":
        return {loan.term_months: loan.amount}
    if loan.repayment_type == "seasonal_installments":
        months = sorted(set(loan.repayment_months))
        share = q(loan.amount / len(months))
        schedule = {m: share for m in months}
        schedule[months[-1]] += loan.amount - share * len(months)  # rounding remainder on the last instalment
        return schedule
    return {}


def amortised_payment(amount: Decimal, annual_rate_pct: Decimal, term_months: int) -> Decimal:
    if amount <= 0 or term_months <= 0:
        return ZERO
    r = annual_rate_pct / Decimal("1200")
    if r == 0:
        return q(amount / term_months)
    factor = (1 + r) ** term_months
    return q(amount * r * factor / (factor - 1))


def validate_input(data: FarmCashFlowInput) -> list[str]:
    """Structural problems that make the projection meaningless. Raised as errors, not warnings."""
    problems = []
    term = data.loan.term_months
    if term < 1 or term > 60:
        problems.append("term_months must be between 1 and 60")
    if data.loan.repayment_type == "seasonal_installments":
        if not data.loan.repayment_months:
            problems.append("seasonal_installments needs at least one repayment month")
        elif any(m < 1 or m > term for m in data.loan.repayment_months):
            problems.append("repayment months must fall within the loan term")
    for crop in data.crops:
        if crop.harvest_month < 1:
            problems.append(f"{crop.crop}: harvest_month must be >= 1")
        if not (ZERO <= crop.sale_share <= 1):
            problems.append(f"{crop.crop}: sale_share must be between 0 and 1")
    for cost in data.costs:
        if cost.month < 1 or cost.month > term:
            problems.append(f"cost '{cost.category}' month {cost.month} is outside the loan term")
        if cost.amount < 0:
            problems.append(f"cost '{cost.category}' is negative")
    return problems


def project_cash_flow(data: FarmCashFlowInput, scenario: Scenario = BASELINE) -> CashFlowResult:
    problems = validate_input(data)
    if problems:
        raise ValueError("; ".join(problems))
    loan, term = data.loan, data.loan.term_months
    warnings: list[str] = []
    rows = [MonthRow(m, month_label(data.start_month, m), ZERO, ZERO, q(data.other_monthly_income), ZERO, ZERO, ZERO,
                     q(data.operating_expenses_monthly), q(data.existing_obligations_monthly), ZERO, ZERO)
            for m in range(1, term + 1)]

    revenue_outside_term = ZERO
    for crop in data.crops:
        month = crop.harvest_month + scenario.harvest_delay_months
        value = harvest_revenue(crop, scenario)
        if month <= term:
            rows[month - 1].harvest_revenue += value
        else:
            revenue_outside_term += value
            warnings.append(f"{crop.crop} harvest ({month_label(data.start_month, month)}) falls after the loan term; "
                            f"{value} {data.currency} is excluded from repayment capacity")
    cost_factor = _factor(scenario.input_cost_change_pct)
    for cost in data.costs:
        amount = q(cost.amount * (cost_factor if cost.kind == "production" else 1))
        if cost.kind == "investment":
            rows[cost.month - 1].investment_costs += amount
        else:
            rows[cost.month - 1].production_costs += amount
    if loan.amount > 0:
        rows[loan.disbursement_month - 1].loan_disbursement = q(loan.amount)

    # Debt service.
    monthly_rate = loan.annual_rate_pct / Decimal("1200")
    outstanding, accrued = loan.amount, ZERO
    if loan.repayment_type == "equal_monthly":
        payment = amortised_payment(loan.amount, loan.annual_rate_pct, term)
        for row in rows:
            interest = q(outstanding * monthly_rate)
            principal = outstanding if row.month == term else min(outstanding, payment - interest)
            row.interest_paid, row.principal_paid = interest, q(principal)
            outstanding -= row.principal_paid
    else:
        schedule = _principal_schedule(loan)
        for row in rows:
            accrued += outstanding * monthly_rate
            if row.month in schedule:
                row.interest_paid = q(accrued)
                row.principal_paid = q(schedule[row.month])
                outstanding -= row.principal_paid
                accrued = ZERO

    balance = q(data.opening_cash_balance)
    for row in rows:
        row.opening_balance = balance
        row.closing_balance = q(row.cash_before_debt_service - row.debt_service)
        balance = row.closing_balance

    return CashFlowResult(scenario, data.currency, rows, _summarise(data, rows, revenue_outside_term), _installments(rows), warnings)


def _installments(rows: list[MonthRow]) -> list[dict]:
    out = []
    for row in rows:
        if row.debt_service <= 0:
            continue
        available = row.cash_before_debt_service
        out.append({"month": row.month, "label": row.label, "due": row.debt_service, "interest": row.interest_paid,
                    "principal": row.principal_paid, "cash_available_before_payment": available,
                    "covered": available >= row.debt_service,
                    "shortfall": q(max(ZERO, row.debt_service - available))})
    return out


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return (numerator / denominator).quantize(Decimal("0.001"), ROUND_HALF_UP) if denominator > 0 else None


def _summarise(data: FarmCashFlowInput, rows: list[MonthRow], revenue_outside_term: Decimal) -> dict:
    def total(attr: str) -> Decimal:
        return sum((getattr(r, attr) for r in rows), ZERO)

    revenue, production = total("harvest_revenue"), total("production_costs")
    other_income, investment = total("other_income"), total("investment_costs")
    operating, existing = total("operating_expenses"), total("existing_obligations")
    interest, principal = total("interest_paid"), total("principal_paid")
    debt_service = interest + principal
    operating_surplus = revenue + other_income - production - operating - existing
    cash_for_debt_service = q(data.opening_cash_balance) + total("loan_disbursement") + operating_surplus - investment
    low = min(rows, key=lambda r: (r.closing_balance, r.month))
    negative = [r.label for r in rows if r.closing_balance < 0]
    harvest_months = [r.month for r in rows if r.harvest_revenue > 0]
    return {
        "harvest_revenue": revenue,
        "revenue_after_loan_term": revenue_outside_term,
        "production_costs": production,
        "investment_costs": investment,
        "gross_farm_margin": revenue - production,
        "other_income": other_income,
        "operating_expenses": operating,
        "existing_obligations": existing,
        "operating_cash_surplus": operating_surplus,
        "loan_amount": data.loan.amount,
        "interest_total": interest,
        "principal_total": principal,
        "new_loan_debt_service": debt_service,
        "cash_available_for_debt_service": cash_for_debt_service,
        "repayment_coverage_ratio": _ratio(cash_for_debt_service, debt_service),
        "production_cost_to_revenue": _ratio(production, revenue),
        "minimum_closing_balance": low.closing_balance,
        "minimum_balance_month": low.label,
        "months_with_negative_balance": negative,
        "first_harvest_month": rows[harvest_months[0] - 1].label if harvest_months else None,
        "ending_balance": rows[-1].closing_balance,
        "average_monthly_income": q((revenue + other_income) / len(rows)),
        "average_monthly_debt_service": q((debt_service + existing) / len(rows)),
    }


def assumptions(data: FarmCashFlowInput) -> list[str]:
    return [
        f"All amounts in {data.currency}; rounded half-up to 0.01 per line item.",
        f"Month 1 = {data.start_month:%Y-%m}; projection covers the {data.loan.term_months}-month loan term.",
        "Harvest revenue = area (ha) x yield (t/ha) x price per tonne x share sold, received in the harvest month.",
        "Interest accrues monthly on the outstanding principal at annual rate / 12 (declining balance).",
        "Loan proceeds are received in month 1; investment costs are not scaled by input-cost scenarios.",
        "Repayment coverage = (opening cash + loan proceeds + inflows - non-debt outflows) / new-loan debt service.",
        "Yields and prices are borrower projections unless marked 'historical' and supported by evidence documents.",
        "Advisory analysis for a human credit officer. It is not a credit decision.",
    ]
