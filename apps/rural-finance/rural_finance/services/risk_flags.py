"""Transparent, configurable advisory risk flags computed from the cash-flow results and the evidence on file.

Each flag carries the rule that fired, the numbers behind it and the rule-set version. The rules read only
financial, agronomic and documentary inputs; the application schema has no protected or sensitive attributes
(see risk_rules.json "excluded_attributes"), so no flag can depend on them.
"""
from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from rural_finance.services.cashflow import CashFlowResult, FarmCashFlowInput, harvest_revenue, q

RULES_PATH = Path(__file__).with_name("risk_rules.json")


@lru_cache
def rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _flag(code: str, severity: str, title: str, explanation: str, evidence: dict) -> dict:
    return {"code": code, "severity": severity, "title": title, "explanation": explanation, "evidence": evidence,
            "rule_version": rules()["version"], "advisory": True}


def _pct_diff(declared: Decimal, computed: Decimal) -> Decimal | None:
    if computed == 0:
        return None
    return q(abs(declared - computed) / computed * 100)


def evaluate_flags(data: FarmCashFlowInput, results: dict[str, CashFlowResult], document_types: set[str],
                   declared_revenue: Decimal | None, declared_costs: Decimal | None) -> list[dict]:
    cfg = rules()
    comfortable, minimum = Decimal(cfg["coverage_comfortable"]), Decimal(cfg["coverage_minimum"])
    base = results["baseline"]
    s = base.summary
    flags: list[dict] = []
    ccy = data.currency

    if s["harvest_revenue"] == 0:
        flags.append(_flag("NO_HARVEST_REVENUE_IN_TERM", "high", "No harvest revenue inside the loan term",
                           "The projection contains no harvest revenue before the loan matures, so repayment capacity "
                           "from farming cannot be shown.", {"revenue_after_loan_term": str(s["revenue_after_loan_term"])}))

    if s["months_with_negative_balance"]:
        flags.append(_flag("SEASONAL_CASHFLOW_SHORTFALL", "high", "Seasonal cash-flow shortfall",
                           f"The baseline cash balance falls below zero in {len(s['months_with_negative_balance'])} "
                           f"month(s); lowest balance {s['minimum_closing_balance']} {ccy} in {s['minimum_balance_month']}.",
                           {"months": s["months_with_negative_balance"], "minimum_balance": str(s["minimum_closing_balance"])}))

    cov = s["repayment_coverage_ratio"]
    if cov is not None and cov < comfortable:
        severity = "high" if cov < minimum else "warning"
        flags.append(_flag("THIN_REPAYMENT_COVERAGE", severity, "Repayment coverage below policy comfort level",
                           f"Baseline repayment coverage is {cov} against a comfort level of {comfortable} "
                           f"(minimum {minimum}).", {"coverage": str(cov), "comfortable": str(comfortable)}))

    uncovered = [i for i in base.installments if not i["covered"]]
    first_harvest = next((r.month for r in base.rows if r.harvest_revenue > 0), None)
    before_harvest = [i for i in base.installments if first_harvest is None or i["month"] < first_harvest]
    delay = results.get("harvest_delay_2_months")
    delay_uncovered = [i for i in delay.installments if not i["covered"]] if delay else []
    if uncovered or before_harvest or delay_uncovered:
        severity = "high" if uncovered else "warning"
        parts = []
        if before_harvest:
            parts.append(f"{len(before_harvest)} instalment(s) fall due before the first harvest ({s['first_harvest_month'] or 'none in term'})")
        if uncovered:
            parts.append(f"{len(uncovered)} baseline instalment(s) exceed the cash available that month")
        if delay_uncovered:
            parts.append(f"a 2-month harvest delay leaves {len(delay_uncovered)} instalment(s) uncovered")
        flags.append(_flag("REPAYMENT_TIMING_MISALIGNMENT", severity, "Repayment timing misaligned with harvest",
                           "; ".join(parts) + ".",
                           {"uncovered_baseline": [{"month": i["label"], "shortfall": str(i["shortfall"])} for i in uncovered],
                            "due_before_first_harvest": [i["label"] for i in before_harvest],
                            "uncovered_if_harvest_delayed": [i["label"] for i in delay_uncovered]}))

    cost_ratio = s["production_cost_to_revenue"]
    cost_shock = results.get("input_costs_plus_20")
    shock_bad = cost_shock is not None and (
        (cost_shock.summary["repayment_coverage_ratio"] or Decimal(0)) < minimum or cost_shock.summary["months_with_negative_balance"])
    if (cost_ratio is not None and cost_ratio > Decimal(cfg["production_cost_to_revenue_max"])) or shock_bad:
        flags.append(_flag("HIGH_INPUT_COST_SENSITIVITY", "warning", "High sensitivity to input costs",
                           f"Production costs are {cost_ratio} of harvest revenue"
                           + ("; a 20% input-cost increase pushes coverage below the minimum or the balance below zero." if shock_bad else "."),
                           {"cost_to_revenue": str(cost_ratio),
                            "coverage_with_costs_plus_20": str(cost_shock.summary["repayment_coverage_ratio"]) if cost_shock else None}))

    shocked = []
    for name in ("yield_minus_20", "price_minus_15", "yield_minus_20_and_price_minus_15"):
        r = results.get(name)
        if r is None:
            continue
        rc = r.summary["repayment_coverage_ratio"]
        if (rc is not None and rc < minimum) or r.summary["months_with_negative_balance"]:
            shocked.append({"scenario": r.scenario.label, "coverage": str(rc), "minimum_balance": str(r.summary["minimum_closing_balance"]),
                            "negative_months": r.summary["months_with_negative_balance"]})
    if shocked:
        single = any(x["scenario"] in {"yield -20%", "price -15%"} for x in shocked)
        flags.append(_flag("YIELD_PRICE_SCENARIO_SENSITIVITY", "high" if single else "warning",
                           "Repayment is sensitive to yield or price shocks",
                           "Under " + "; ".join(x["scenario"] for x in shocked) + " the borrower cannot cover debt service "
                           "from projected cash without a negative balance or coverage below the minimum.", {"scenarios": shocked}))

    missing = [label for code, label in cfg["required_documents"].items() if code not in document_types]
    if missing:
        flags.append(_flag("MISSING_SUPPORTING_DOCUMENTATION", "warning" if len(missing) == 1 else "high",
                           "Missing supporting documentation", "Not on file: " + "; ".join(missing) + ".",
                           {"missing": [c for c in cfg["required_documents"] if c not in document_types]}))
    projected_only = [c.crop for c in data.crops if c.yield_basis != "historical"]
    if projected_only and "yield_or_sales_evidence" not in document_types:
        flags.append(_flag("UNSUPPORTED_YIELD_ASSUMPTION", "warning", "Yield assumptions not supported by evidence",
                           f"Yields for {', '.join(projected_only)} are projections and no yield or sales evidence is on file.",
                           {"crops": projected_only}))

    computed_revenue = sum((harvest_revenue(c) for c in data.crops), Decimal(0))
    computed_costs = sum((c.amount for c in data.costs if c.kind == "production"), Decimal(0))
    inconsistencies = []
    for label, declared, computed, tol in (
        ("annual revenue", declared_revenue, computed_revenue, Decimal(cfg["declared_revenue_tolerance_pct"])),
        ("production costs", declared_costs, computed_costs, Decimal(cfg["declared_cost_tolerance_pct"])),
    ):
        if declared is None:
            continue
        diff = _pct_diff(declared, computed)
        if diff is not None and diff > tol:
            inconsistencies.append({"figure": label, "declared": str(declared), "computed_from_plan": str(computed),
                                    "difference_pct": str(diff), "tolerance_pct": str(tol)})
    if inconsistencies:
        flags.append(_flag("INCONSISTENT_BORROWER_FIGURES", "warning", "Borrower-provided figures are inconsistent",
                           "; ".join(f"declared {i['figure']} {i['declared']} vs {i['computed_from_plan']} computed from the "
                                     f"crop and cost plan ({i['difference_pct']}% apart)" for i in inconsistencies) + ".",
                           {"items": inconsistencies}))
    order = {"high": 0, "warning": 1, "info": 2}
    return sorted(flags, key=lambda f: order[f["severity"]])
