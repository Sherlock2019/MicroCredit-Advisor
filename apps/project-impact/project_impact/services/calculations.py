"""Deterministic project-monitoring calculations. Decimal money, explicit currency, no LLM.

Definitions (returned with every result):
  * Commitments are signed obligations; actual expenditure is money disbursed/spent. They are never summed together.
  * Progress = milestone progress weighted by weight_pct (weights must total 100).
  * Earned-value metrics: BAC = total budget, PV = BAC x planned progress, EV = BAC x actual progress, AC = actual
    expenditure; CPI = EV/AC, SPI = EV/PV, EAC = BAC/CPI (cost-performance forecast), VAC = BAC - EAC.
  * Indicator attainment = (actual - baseline) / (target - baseline). Output attainment shows delivery; it does not
    show outcomes or impact, and no indicator here establishes causal attribution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CALC_VERSION = "project-calculations/1.0.0"
CENT, PCT = Decimal("0.01"), Decimal("0.1")
ZERO, HUNDRED = Decimal("0"), Decimal("100")


def money(v: Decimal) -> Decimal:
    return v.quantize(CENT, ROUND_HALF_UP)


def pct(v: Decimal) -> Decimal:
    return v.quantize(PCT, ROUND_HALF_UP)


def ratio(n: Decimal, d: Decimal) -> Decimal | None:
    return (n / d).quantize(Decimal("0.001"), ROUND_HALF_UP) if d else None


@dataclass(frozen=True)
class MilestoneIn:
    code: str
    title: str
    component: str
    planned_start: date
    planned_end: date
    actual_start: date | None
    actual_end: date | None
    planned_progress_pct: Decimal
    actual_progress_pct: Decimal
    weight_pct: Decimal
    status: str
    has_evidence: bool
    responsible_unit: str = ""


@dataclass(frozen=True)
class BudgetLineIn:
    component: str
    budget: Decimal
    committed: Decimal
    actual: Decimal


@dataclass(frozen=True)
class IndicatorIn:
    code: str
    name: str
    level: str
    unit: str
    baseline: Decimal
    target: Decimal
    actual: Decimal | None
    reporting_period: str | None
    data_source: str | None
    verification_status: str
    has_source_document: bool


@dataclass(frozen=True)
class ReportIn:
    report_type: str
    period_label: str
    due_date: date
    received_date: date | None


# --------------------------------------------------------------------------------------------------------- progress
def weighted_progress(milestones: list[MilestoneIn]) -> dict:
    active = [m for m in milestones if m.status != "cancelled"]
    total_weight = sum((m.weight_pct for m in active), ZERO)
    if total_weight == 0:
        return {"planned_pct": None, "actual_pct": None, "gap_pp": None, "weights_total": ZERO, "weights_valid": False}
    planned = sum((m.planned_progress_pct * m.weight_pct for m in active), ZERO) / total_weight
    actual = sum((m.actual_progress_pct * m.weight_pct for m in active), ZERO) / total_weight
    return {"planned_pct": pct(planned), "actual_pct": pct(actual), "gap_pp": pct(planned - actual),
            "weights_total": total_weight, "weights_valid": total_weight == HUNDRED}


def time_elapsed_pct(start: date, end: date, as_of: date) -> Decimal:
    total = (end - start).days
    if total <= 0:
        return HUNDRED
    return pct(min(HUNDRED, max(ZERO, Decimal((as_of - start).days) / Decimal(total) * HUNDRED)))


def milestone_status(m: MilestoneIn, as_of: date) -> dict:
    """Derived schedule status. The stored status is the implementer's report; this is the rule-based check."""
    issues = []
    if m.status != "completed" and m.status != "cancelled" and m.planned_end < as_of:
        issues.append({"code": "OVERDUE", "detail": f"planned end {m.planned_end} passed; {m.actual_progress_pct}% complete",
                       "days_overdue": (as_of - m.planned_end).days})
    if m.actual_start is None and m.planned_start < as_of and m.status != "cancelled":
        issues.append({"code": "NOT_STARTED", "detail": f"planned start {m.planned_start} passed without a recorded start",
                       "days_late": (as_of - m.planned_start).days})
    gap = m.planned_progress_pct - m.actual_progress_pct
    if gap >= 10:
        issues.append({"code": "BEHIND_PLAN", "detail": f"{m.actual_progress_pct}% actual vs {m.planned_progress_pct}% planned",
                       "gap_pp": pct(gap)})
    if (m.status == "completed" or m.actual_progress_pct > 0) and not m.has_evidence:
        issues.append({"code": "MISSING_EVIDENCE", "detail": "progress reported without an evidence document"})
    if m.status == "completed" and m.actual_progress_pct < HUNDRED:
        issues.append({"code": "INCONSISTENT_STATUS", "detail": "marked completed with progress below 100%"})
    derived = "completed" if m.status == "completed" else "delayed" if any(i["code"] in {"OVERDUE", "NOT_STARTED", "BEHIND_PLAN"} for i in issues) \
        else "on_track" if m.actual_start else "not_started"
    return {"code": m.code, "title": m.title, "component": m.component, "reported_status": m.status, "derived_status": derived,
            "planned_progress_pct": m.planned_progress_pct, "actual_progress_pct": m.actual_progress_pct, "weight_pct": m.weight_pct,
            "planned_end": m.planned_end.isoformat(), "responsible_unit": m.responsible_unit, "issues": issues}


# ----------------------------------------------------------------------------------------------------------- budget
def budget_status(lines: list[BudgetLineIn], currency: str, planned_pct: Decimal | None, actual_pct: Decimal | None) -> dict:
    components = []
    for line in lines:
        components.append({
            "component": line.component, "budget": money(line.budget), "committed": money(line.committed),
            "actual_expenditure": money(line.actual), "remaining_budget": money(line.budget - line.actual),
            "uncommitted_budget": money(line.budget - line.committed),
            "utilisation_pct": pct(line.actual / line.budget * HUNDRED) if line.budget else None,
            "commitment_pct": pct(line.committed / line.budget * HUNDRED) if line.budget else None,
            "overspent": line.actual > line.budget, "overcommitted": line.committed > line.budget,
        })
    bac = sum((ln.budget for ln in lines), ZERO)
    ac = sum((ln.actual for ln in lines), ZERO)
    committed = sum((ln.committed for ln in lines), ZERO)
    totals = {"currency": currency, "budget": money(bac), "committed": money(committed), "actual_expenditure": money(ac),
              "remaining_budget": money(bac - ac), "uncommitted_budget": money(bac - committed),
              "utilisation_pct": pct(ac / bac * HUNDRED) if bac else None}
    evm: dict = {"available": False}
    if bac and planned_pct is not None and actual_pct is not None:
        pv, ev = money(bac * planned_pct / HUNDRED), money(bac * actual_pct / HUNDRED)
        cpi, spi = ratio(ev, ac), ratio(ev, pv)
        eac = money(bac / (ev / ac)) if ac and ev else None
        evm = {"available": True, "planned_value": pv, "earned_value": ev, "actual_cost": money(ac),
               "cost_variance": money(ev - ac), "schedule_variance": money(ev - pv), "cpi": cpi, "spi": spi,
               "estimate_at_completion": eac, "variance_at_completion": money(bac - eac) if eac is not None else None}
    return {"components": components, "totals": totals, "earned_value": evm, "calc_version": CALC_VERSION}


def spending_velocity(period_amounts: list[tuple[str, Decimal]], remaining: Decimal, window: int = 4) -> dict:
    if not period_amounts:
        return {"periods": 0, "average_per_period": None, "periods_to_exhaust_at_average": None}
    recent = [a for _, a in period_amounts[-window:]]
    avg = money(sum(recent, ZERO) / len(recent))
    return {"periods": len(period_amounts), "window": len(recent), "average_per_period": avg,
            "latest_period": period_amounts[-1][0], "latest_amount": money(period_amounts[-1][1]),
            "periods_to_exhaust_at_average": pct(remaining / avg) if avg > 0 else None}


# ------------------------------------------------------------------------------------------------------- indicators
def indicator_progress(ind: IndicatorIn, expected_pct: Decimal | None = None) -> dict:
    warnings = []
    attainment = None
    span = ind.target - ind.baseline
    if ind.actual is None:
        warnings.append("No value reported yet.")
    elif span == 0:
        warnings.append("Target equals baseline; attainment is undefined.")
    else:
        attainment = pct((ind.actual - ind.baseline) / span * HUNDRED)
    if ind.verification_status in {"unverified", "disputed"}:
        warnings.append(f"Reported value is {ind.verification_status}; verify before citing it.")
    if not ind.data_source:
        warnings.append("No data source recorded.")
    if not ind.has_source_document and ind.actual is not None:
        warnings.append("No source document linked to the reported value.")
    if ind.level == "impact":
        warnings.append("Impact indicator: attainment does not establish attribution to the project without a counterfactual.")
    elif ind.level == "outcome":
        warnings.append("Outcome indicator: changes may have causes outside the project.")
    gap = None
    if attainment is not None and expected_pct is not None:
        gap = pct(expected_pct - attainment)
    return {"code": ind.code, "name": ind.name, "level": ind.level, "unit": ind.unit, "baseline": ind.baseline,
            "target": ind.target, "actual": ind.actual, "attainment_pct": attainment, "expected_pct_by_now": expected_pct,
            "gap_to_expected_pp": gap, "reporting_period": ind.reporting_period, "data_source": ind.data_source,
            "verification_status": ind.verification_status, "quality_warnings": warnings}


# ---------------------------------------------------------------------------------------------------------- reports
def reporting_completeness(reports: list[ReportIn], as_of: date) -> dict:
    due = [r for r in reports if r.due_date <= as_of]
    received = [r for r in due if r.received_date is not None]
    late = [r for r in received if r.received_date > r.due_date]
    missing = [{"report_type": r.report_type, "period": r.period_label, "due_date": r.due_date.isoformat(),
                "days_overdue": (as_of - r.due_date).days} for r in due if r.received_date is None]
    return {"due": len(due), "received": len(received), "late": len(late), "missing": missing,
            "completeness_pct": pct(Decimal(len(received)) / Decimal(len(due)) * HUNDRED) if due else None}
