# VENDORED UNCHANGED from github.com/Sherlock2019/CreditpappraisalFlowise
#   path:   bank-credit-ai-poc/backend/app/policy/loan_policy.py
#   commit: d3ff23f5c01ceaab478b1021417f29c592d0ceff
#   sha256 of source: d4ef68e0d5b69863ff61d2c87ed43d2d44c66c7812f59dc78c880007c7d793a7
# Do not edit: change the upstream file and re-vendor (integrations/creditpappraisal-adapter/SOURCE.md).
from __future__ import annotations

from math import isfinite
from typing import Any

FRAUD_SEVERITY_BY_INDICATOR = {
    "suspicious_invoice_duplication": 3,
    "related_party_invoices": 2,
    "unexplained_deposits": 2,
    "valuation_overstatement": 3,
    "tax_arrears": 2,
    "weak_collateral": 1,
    "income_mismatch": 3,
    "missing_documents": 2,
}

NEXT_STEPS = [
    "Credit appraisal completed",
    "Loan policy scoring",
    "Approval Committee review",
    "Final Decision",
    "Send decision email to customer",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if isfinite(number) else default


def _round_money(value: float) -> float:
    return round(value + 1e-9, 2)


def calculate_dti(monthly_debt_payments: float, monthly_income: float) -> dict[str, Any]:
    monthly_debt_payments = _safe_float(monthly_debt_payments)
    monthly_income = _safe_float(monthly_income)
    if monthly_income <= 0:
        return {
            "value_pct": None,
            "band": "Insufficient Evidence",
            "assessment": "Monthly income is missing or zero; repayment capacity cannot be assessed.",
        }

    value_pct = (monthly_debt_payments / monthly_income) * 100
    if value_pct < 30:
        band = "Excellent"
        assessment = "Repayment capacity strong"
    elif value_pct < 40:
        band = "Good"
        assessment = "Repayment capacity acceptable"
    elif value_pct <= 45:
        band = "Review"
        assessment = "Repayment capacity requires manual review"
    elif value_pct <= 50:
        band = "High Risk"
        assessment = "Repayment capacity is stressed"
    else:
        band = "Often Declined"
        assessment = "Repayment capacity is above common decline threshold"

    return {"value_pct": round(value_pct, 2), "band": band, "assessment": assessment}


def calculate_ltv(loan_amount: float, collateral_value: float) -> dict[str, Any]:
    loan_amount = _safe_float(loan_amount)
    collateral_value = _safe_float(collateral_value)
    if collateral_value <= 0:
        return {
            "value_pct": None,
            "band": "Insufficient Evidence",
            "assessment": "Collateral value is missing or zero; collateral coverage cannot be assessed.",
        }

    value_pct = (loan_amount / collateral_value) * 100
    if value_pct < 60:
        band = "Low"
        assessment = "Collateral coverage is strong, but repayment capacity remains primary"
    elif value_pct < 80:
        band = "Medium"
        assessment = "Collateral coverage acceptable but not primary approval reason"
    elif value_pct <= 90:
        band = "High"
        assessment = "Collateral coverage requires manual review"
    else:
        band = "Very High"
        assessment = "Collateral coverage is weak and requires committee attention"

    return {"value_pct": round(value_pct, 2), "band": band, "assessment": assessment}


def _fraud_severity(fraud_indicators: list[str] | None, missing_documents: list[str] | None = None) -> int:
    indicators = {str(indicator).strip() for indicator in fraud_indicators or [] if str(indicator).strip()}
    severity = max((FRAUD_SEVERITY_BY_INDICATOR.get(indicator, 1) for indicator in indicators), default=0)
    if missing_documents:
        severity = max(severity, FRAUD_SEVERITY_BY_INDICATOR["missing_documents"])
    return severity


def calculate_interest_rate(dti_band: str, ltv_band: str, fraud_severity: int, base_rate: float = 8.5) -> dict[str, Any]:
    base_rate = _safe_float(base_rate, 8.5)
    dti_band = dti_band or "Insufficient Evidence"
    ltv_band = ltv_band or "Insufficient Evidence"

    if fraud_severity >= 3 or dti_band in {"Often Declined"} or ltv_band in {"Very High"}:
        risk_spread = 5.0
    elif dti_band in {"High Risk"} or ltv_band in {"High"}:
        risk_spread = 3.5
    elif dti_band in {"Review"} or ltv_band in {"Medium"}:
        risk_spread = 2.0
    elif dti_band in {"Good"}:
        risk_spread = 1.0
    elif dti_band in {"Excellent"} and ltv_band in {"Low"}:
        risk_spread = 0.5
    else:
        risk_spread = 5.0

    estimated_rate = base_rate + risk_spread
    return {
        "base_rate_pct": round(base_rate, 2),
        "risk_spread_pct": round(risk_spread, 2),
        "estimated_annual_rate_pct": round(estimated_rate, 2),
    }


def calculate_monthly_payment(loan_amount: float, annual_rate: float, term_months: int = 60) -> float:
    loan_amount = _safe_float(loan_amount)
    annual_rate = _safe_float(annual_rate)
    try:
        term_months = int(term_months)
    except (TypeError, ValueError):
        term_months = 60
    if term_months <= 0:
        term_months = 60
    if loan_amount <= 0:
        return 0.0

    monthly_rate = annual_rate / 12 / 100
    if monthly_rate <= 0:
        return _round_money(loan_amount / term_months)
    factor = (1 + monthly_rate) ** term_months
    return _round_money(loan_amount * monthly_rate * factor / (factor - 1))


def determine_recommendation(
    dti_pct: float | None,
    ltv_pct: float | None,
    fraud_severity: int,
    missing_docs: list[str] | None,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    missing_docs = missing_docs or []
    if missing_docs:
        reason_codes.append("missing_documents")

    if dti_pct is None:
        reason_codes.append("insufficient_monthly_income")
    if ltv_pct is None:
        reason_codes.append("insufficient_collateral_value")
    if fraud_severity >= 3:
        reason_codes.append("high_fraud_severity")
    elif fraud_severity > 0:
        reason_codes.append("fraud_indicators_present")

    if dti_pct is None or ltv_pct is None:
        recommendation = "Insufficient Evidence"
        committee_required = True
    elif fraud_severity >= 3:
        recommendation = "Enhanced Due Diligence Required"
        committee_required = True
    elif dti_pct > 50:
        recommendation = "Decline Recommended"
        committee_required = True
        reason_codes.append("dti_above_50")
    elif dti_pct > 45 or ltv_pct > 90:
        recommendation = "High Risk / Approval Committee Required"
        committee_required = True
        if dti_pct > 45:
            reason_codes.append("dti_above_45")
        if ltv_pct > 90:
            reason_codes.append("ltv_above_90")
    elif dti_pct >= 40 or ltv_pct >= 80:
        recommendation = "Manual Review Required"
        committee_required = True
        if dti_pct >= 40:
            reason_codes.append("dti_40_or_above")
        if ltv_pct >= 80:
            reason_codes.append("ltv_80_or_above")
    else:
        recommendation = "Conditionally Acceptable"
        committee_required = False

    return {
        "recommendation": recommendation,
        "committee_required": committee_required,
        "final_decision_allowed": False,
        "human_review_required": True,
        "reason_codes": sorted(set(reason_codes)),
    }


def score_loan_policy(payload: dict[str, Any]) -> dict[str, Any]:
    loan_amount = _safe_float(payload.get("loan_amount"))
    collateral_value = _safe_float(payload.get("collateral_value"))
    monthly_income = _safe_float(payload.get("monthly_income"))
    monthly_debt_payments = _safe_float(payload.get("monthly_debt_payments"))
    term_months = int(payload.get("term_months") or 60)
    fraud_indicators = list(payload.get("fraud_indicators") or [])
    missing_documents = list(payload.get("missing_documents") or [])

    dti = calculate_dti(monthly_debt_payments, monthly_income)
    ltv = calculate_ltv(loan_amount, collateral_value)
    fraud_severity = _fraud_severity(fraud_indicators, missing_documents)
    interest = calculate_interest_rate(dti["band"], ltv["band"], fraud_severity)
    interest["estimated_monthly_payment"] = calculate_monthly_payment(
        loan_amount,
        interest["estimated_annual_rate_pct"],
        term_months,
    )
    policy = determine_recommendation(dti["value_pct"], ltv["value_pct"], fraud_severity, missing_documents)

    return {
        "customer_id": str(payload.get("customer_id", "")),
        "assessment_id": payload.get("assessment_id"),
        "dti": dti,
        "ltv": ltv,
        "interest": interest,
        "policy": policy,
        "fraud": {
            "indicators": fraud_indicators,
            "severity": fraud_severity,
        },
        "missing_documents": missing_documents,
        "next_steps": NEXT_STEPS,
    }
