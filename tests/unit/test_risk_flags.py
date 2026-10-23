from decimal import Decimal as D

import pytest
from pydantic import ValidationError
from rural_finance.schemas import ApplicationCreate
from rural_finance.services.cashflow import STANDARD_SCENARIOS, project_cash_flow
from rural_finance.services.risk_flags import evaluate_flags, rules

from tests.fixtures import engine_input, finance_case

ALL_DOCS = {"farm_business_plan", "yield_or_sales_evidence", "land_use_evidence"}


def flags_for(key: str, docs: set[str]):
    data = engine_input(key)
    payload = finance_case(key)["payload"]
    results = {s.name: project_cash_flow(data, s) for s in STANDARD_SCENARIOS}
    declared_rev = D(str(payload["declared_annual_revenue"])) if payload.get("declared_annual_revenue") else None
    declared_cost = D(str(payload["declared_production_costs"])) if payload.get("declared_production_costs") else None
    return {f["code"]: f for f in evaluate_flags(data, results, docs, declared_rev, declared_cost)}


def test_demo_a_manageable_baseline_sensitive_to_combined_shock():
    flags = flags_for("demo-a-rice-coop", ALL_DOCS)
    assert "SEASONAL_CASHFLOW_SHORTFALL" not in flags
    assert "THIN_REPAYMENT_COVERAGE" not in flags
    assert flags["YIELD_PRICE_SCENARIO_SENSITIVITY"]["severity"] == "warning"  # combined shock only
    assert "INCONSISTENT_BORROWER_FIGURES" not in flags


def test_liquidity_gap_flags_shortfall_and_timing():
    flags = flags_for("case-liquidity-gap", ALL_DOCS)
    assert flags["SEASONAL_CASHFLOW_SHORTFALL"]["severity"] == "high"
    assert flags["REPAYMENT_TIMING_MISALIGNMENT"]["evidence"]["due_before_first_harvest"]


def test_missing_evidence_case():
    flags = flags_for("case-missing-evidence", {"farm_business_plan"})
    assert set(flags["MISSING_SUPPORTING_DOCUMENTATION"]["evidence"]["missing"]) == {"yield_or_sales_evidence", "land_use_evidence"}
    assert "UNSUPPORTED_YIELD_ASSUMPTION" in flags
    assert flags["INCONSISTENT_BORROWER_FIGURES"]["evidence"]["items"][0]["figure"] == "annual revenue"
    assert flags["REPAYMENT_TIMING_MISALIGNMENT"]["evidence"]["uncovered_if_harvest_delayed"]


def test_flags_are_advisory_versioned_and_explained():
    for flag in flags_for("case-liquidity-gap", set()).values():
        assert flag["advisory"] is True
        assert flag["rule_version"] == rules()["version"]
        assert flag["explanation"] and flag["evidence"] is not None


@pytest.mark.parametrize("attribute", rules()["excluded_attributes"])
def test_protected_attributes_cannot_enter_the_application(attribute):
    payload = {**finance_case("demo-a-rice-coop")["payload"], attribute: "x"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ApplicationCreate.model_validate(payload)
    assert attribute not in ApplicationCreate.model_fields


def test_pseudonym_must_not_look_like_a_name():
    with pytest.raises(ValidationError):
        ApplicationCreate.model_validate({**finance_case("demo-a-rice-coop")["payload"], "borrower_pseudonym": "Jane Doe"})
