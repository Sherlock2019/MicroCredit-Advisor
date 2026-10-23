"""Adapter: Decimal in, Decimal out, around the Banking copilot's float-based policy functions.

Only the source's public functions are used: calculate_monthly_payment, calculate_dti.
The agricultural engine is authoritative for money; this adapter supplies
  * an independent amortisation cross-check (the two implementations must agree to the cent), and
  * the Banking copilot's obligation-burden bands, reused as an advisory indicator on monthly averages.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from ifad_credit_adapter.vendor import loan_policy

ADAPTER_VERSION = "creditpappraisal-adapter/1.0.0"
SOURCE_COMMIT = "d3ff23f5c01ceaab478b1021417f29c592d0ceff"
CENT = Decimal("0.01")


class CreditPolicyAdapter:
    version = ADAPTER_VERSION

    @staticmethod
    def amortised_monthly_payment(principal: Decimal, annual_rate_pct: Decimal, term_months: int) -> Decimal:
        value = loan_policy.calculate_monthly_payment(float(principal), float(annual_rate_pct), term_months)
        return Decimal(str(value)).quantize(CENT, ROUND_HALF_UP)

    @staticmethod
    def obligation_burden(monthly_debt_service: Decimal, monthly_income: Decimal) -> dict:
        """Banking DTI bands applied to average monthly figures. Advisory only: seasonal income makes a monthly
        average misleading, so the cash-flow engine's month-by-month view takes precedence."""
        result = loan_policy.calculate_dti(float(monthly_debt_service), float(monthly_income))
        return {"ratio_pct": result["value_pct"], "band": result["band"], "assessment": result["assessment"],
                "source": f"CreditpappraisalFlowise loan_policy.calculate_dti @ {SOURCE_COMMIT[:7]}",
                "caveat": "Average-month ratio; seasonal borrowers are assessed on the monthly cash-flow table."}
