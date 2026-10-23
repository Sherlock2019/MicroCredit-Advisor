from datetime import date
from decimal import Decimal as D

import pytest
from rural_finance.services.cashflow import (
    STANDARD_SCENARIOS,
    CostLine,
    CropPlan,
    LoanTerms,
    Scenario,
    amortised_payment,
    harvest_revenue,
    month_label,
    project_cash_flow,
)

from tests.fixtures import engine_input, simple_input


def run_all(data):
    return {s.name: project_cash_flow(data, s) for s in STANDARD_SCENARIOS}


def test_demo_a_baseline_matches_hand_calculation():
    """Demo A: 12,000 USD at 14% (declining balance), instalments after both harvests, 22,000 revenue, 9,000 costs."""
    s = project_cash_flow(engine_input("demo-a-rice-coop")).summary
    assert s["harvest_revenue"] == D("22000.00")
    assert s["production_costs"] == D("9000.00")
    assert s["investment_costs"] == D("3000.00")
    assert s["existing_obligations"] == D("2400.00")
    # Interest: 12,000 x 14%/12 x 6 months = 840; 6,000 x 14%/12 x 6 months = 420.
    assert s["interest_total"] == D("1260.00")
    assert s["new_loan_debt_service"] == D("13260.00")
    # (1,500 opening + 12,000 loan + 22,000 - 9,000 - 1,800 - 2,400 - 3,000) / 13,260
    assert s["cash_available_for_debt_service"] == D("19300.00")
    assert s["repayment_coverage_ratio"] == D("1.456")
    assert s["minimum_closing_balance"] == D("2250.00") and s["minimum_balance_month"] == "2026-07"
    assert s["ending_balance"] == D("6040.00")
    assert s["months_with_negative_balance"] == []


def test_demo_a_shocks_yield_price_and_combined():
    r = run_all(engine_input("demo-a-rice-coop"))
    assert r["yield_minus_20"].summary["harvest_revenue"] == D("17600.00")
    assert r["price_minus_15"].summary["harvest_revenue"] == D("18700.00")
    combined = r["yield_minus_20_and_price_minus_15"].summary
    assert combined["harvest_revenue"] == D("14960.00")
    assert combined["repayment_coverage_ratio"] == D("0.925")
    assert combined["months_with_negative_balance"] == ["2027-02"]
    assert combined["ending_balance"] == D("-1000.00")


def test_balance_identity_holds_every_month():
    for result in run_all(engine_input("demo-a-rice-coop")).values():
        for row in result.rows:
            inflow = row.harvest_revenue + row.other_income + row.loan_disbursement
            outflow = (row.production_costs + row.investment_costs + row.operating_expenses + row.existing_obligations
                       + row.debt_service)
            assert row.closing_balance == row.opening_balance + inflow - outflow
        assert result.summary["principal_total"] == D("12000.00")


def test_liquidity_gap_case_is_negative_before_harvest_and_recovers():
    s = project_cash_flow(engine_input("case-liquidity-gap")).summary
    assert s["months_with_negative_balance"] == ["2027-01", "2027-02", "2027-03"]
    assert s["first_harvest_month"] == "2027-04"
    assert s["ending_balance"] > 0


def test_equal_monthly_amortisation_fully_repays_principal():
    data = engine_input("case-liquidity-gap")
    result = project_cash_flow(data)
    assert sum(r.principal_paid for r in result.rows) == D("1500.00")
    payment = amortised_payment(D("1500"), D("18"), 10)
    assert payment == D("162.65")  # 1,500 x 0.015 x 1.015^10 / (1.015^10 - 1)
    assert all(abs(r.debt_service - payment) <= D("0.05") for r in result.rows[:-1])


def test_harvest_delay_moves_revenue_outside_term_and_warns():
    result = project_cash_flow(engine_input("case-missing-evidence"), Scenario("late", harvest_delay_months=2))
    assert result.summary["harvest_revenue"] == D("0")
    assert result.summary["revenue_after_loan_term"] == D("3456.00")
    assert result.warnings and "after the loan term" in result.warnings[0]
    assert result.installments[0]["covered"] is False


def test_zero_income_gives_no_crash_and_shortfall():
    data = simple_input(crops=(CropPlan("maize", D("1"), D("0"), D("300"), 6),))
    s = project_cash_flow(data).summary
    assert s["harvest_revenue"] == D("0.00")
    assert s["months_with_negative_balance"]
    assert s["production_cost_to_revenue"] is None


def test_no_loan_means_no_coverage_ratio():
    s = project_cash_flow(simple_input(loan=LoanTerms(D("0"), D("12"), 6, "bullet"))).summary
    assert s["new_loan_debt_service"] == D("0") and s["repayment_coverage_ratio"] is None


def test_money_is_decimal_quantised_to_cents():
    row = project_cash_flow(engine_input("demo-a-rice-coop")).rows[5]
    for value in (row.harvest_revenue, row.interest_paid, row.closing_balance):
        assert isinstance(value, D) and value == value.quantize(D("0.01"))


def test_harvest_revenue_formula_and_sale_share():
    crop = CropPlan("rice", D("2"), D("4"), D("400"), 3, D("0.5"))
    assert harvest_revenue(crop) == D("1600.00")


@pytest.mark.parametrize("bad, message", [
    (dict(loan=LoanTerms(D("100"), D("10"), 6, "seasonal_installments", ())), "at least one repayment month"),
    (dict(loan=LoanTerms(D("100"), D("10"), 6, "seasonal_installments", (9,))), "within the loan term"),
    (dict(costs=(CostLine("x", D("10"), 12),)), "outside the loan term"),
    (dict(costs=(CostLine("x", D("-1"), 1),)), "negative"),
])
def test_invalid_inputs_are_rejected(bad, message):
    with pytest.raises(ValueError, match=message):
        project_cash_flow(simple_input(**bad))


def test_month_labels_cross_year():
    assert month_label(date(2026, 11, 1), 3) == "2027-01"
