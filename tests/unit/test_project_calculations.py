import json
from datetime import date
from decimal import Decimal as D

from project_impact.services import calculations as calc

from tests.fixtures import DATA

AS_OF = date(2026, 6, 30)


def demo_b():
    return json.loads((DATA / "projects.json").read_text())["detailed"][0]


def demo_b_milestones():
    out = []
    for m in demo_b()["milestones"]:
        out.append(calc.MilestoneIn(m["activity_code"], m["title"], m["component"], date.fromisoformat(m["planned_start"]),
                                    date.fromisoformat(m["planned_end"]),
                                    date.fromisoformat(m["actual_start"]) if m.get("actual_start") else None,
                                    date.fromisoformat(m["actual_end"]) if m.get("actual_end") else None,
                                    D(str(m["planned_progress_pct"])), D(str(m["actual_progress_pct"])), D(str(m["weight_pct"])),
                                    m["status"], bool(m.get("evidence"))))
    return out


def test_demo_b_weighted_progress_shows_18_point_gap():
    p = calc.weighted_progress(demo_b_milestones())
    assert (p["planned_pct"], p["actual_pct"], p["gap_pp"]) == (D("60.0"), D("42.0"), D("18.0"))
    assert p["weights_valid"] is True


def test_demo_b_earned_value_and_no_commitment_conflation():
    lines = [calc.BudgetLineIn(b["component"], D(str(b["budget_amount"])), D(str(b["committed_amount"])), D(str(b["actual_expenditure"])))
             for b in demo_b()["budget"]]
    view = calc.budget_status(lines, "USD", D("60"), D("42"))
    t, evm = view["totals"], view["earned_value"]
    assert t["budget"] == D("5000000.00") and t["actual_expenditure"] == D("2450000.00") and t["committed"] == D("3400000.00")
    assert t["remaining_budget"] == D("2550000.00")  # budget - expenditure, never budget - commitments - expenditure
    assert t["uncommitted_budget"] == D("1600000.00")
    assert evm["planned_value"] == D("3000000.00") and evm["earned_value"] == D("2100000.00")
    assert evm["cpi"] == D("0.857") and evm["spi"] == D("0.700")
    assert evm["estimate_at_completion"] == D("5833333.33")


def test_milestone_rules_on_demo_b():
    status = {m.code: calc.milestone_status(m, AS_OF) for m in demo_b_milestones()}
    codes = lambda c: {i["code"] for i in status[c]["issues"]}  # noqa: E731
    assert "OVERDUE" in codes("IRR-2.1")
    assert "NOT_STARTED" in codes("IRR-1.3")
    assert {"MISSING_EVIDENCE", "BEHIND_PLAN"} <= codes("FS-2.2")
    assert codes("ME-4.1") == {"MISSING_EVIDENCE"}
    assert status["IRR-1.1"]["derived_status"] == "completed" and not codes("IRR-1.1")
    assert status["IRR-1.2"]["derived_status"] == "delayed"


def test_indicator_attainment_and_warnings():
    ind = calc.IndicatorIn("IND-01", "Farmers reached", "output", "persons", D("0"), D("10000"), D("6200"), "2026-Q1",
                           "progress report", "partially_verified", True)
    r = calc.indicator_progress(ind, D("60"))
    assert r["attainment_pct"] == D("62.0") and r["gap_to_expected_pp"] == D("-2.0")
    yield_ind = calc.IndicatorIn("IND-06", "Yield", "outcome", "t/ha", D("2.8"), D("4.0"), D("3.3"), "2025", None, "unverified", False)
    w = calc.indicator_progress(yield_ind)
    assert w["attainment_pct"] == D("41.7")
    assert any("unverified" in x for x in w["quality_warnings"]) and any("No data source" in x for x in w["quality_warnings"])
    impact = calc.indicator_progress(calc.IndicatorIn("IND-07", "Income", "impact", "%", D("0"), D("40"), None, None, "x", "unverified", False))
    assert impact["attainment_pct"] is None and any("attribution" in x for x in impact["quality_warnings"])


def test_target_equal_to_baseline_is_undefined_not_division_error():
    r = calc.indicator_progress(calc.IndicatorIn("X", "x", "output", "u", D("5"), D("5"), D("5"), None, "s", "verified", True))
    assert r["attainment_pct"] is None


def test_reporting_completeness_counts_only_due_reports():
    reports = [calc.ReportIn("q", "Q1", date(2026, 4, 30), date(2026, 4, 29)), calc.ReportIn("q", "Q2", date(2026, 5, 30), None),
               calc.ReportIn("q", "Q3", date(2026, 9, 30), None)]
    r = calc.reporting_completeness(reports, AS_OF)
    assert (r["due"], r["received"], r["completeness_pct"]) == (2, 1, D("50.0"))
    assert [m["period"] for m in r["missing"]] == ["Q2"]


def test_overspend_detection_and_velocity():
    view = calc.budget_status([calc.BudgetLineIn("grants", D("100"), D("120"), D("110"))], "USD", None, None)
    assert view["components"][0]["overspent"] and view["components"][0]["overcommitted"]
    assert view["earned_value"] == {"available": False}
    v = calc.spending_velocity([("Q1", D("10")), ("Q2", D("20")), ("Q3", D("30"))], D("100"), window=2)
    assert v["average_per_period"] == D("25.00") and v["periods_to_exhaust_at_average"] == D("4.0")


def test_time_elapsed():
    assert calc.time_elapsed_pct(date(2024, 7, 1), date(2028, 6, 30), AS_OF) == D("49.9")
