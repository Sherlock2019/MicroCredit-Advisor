"""End-to-end business workflows through the gateway, as the demo is presented."""
from io import BytesIO

import pytest

from tests.conftest import auth, find_project
from tests.fixtures import finance_case

pytestmark = pytest.mark.e2e


def test_finance_application_document_analysis_review(gateway, unique):
    analyst, reviewer = auth("fatima.finance"), auth("kofi.credit")
    payload = {**finance_case("demo-a-rice-coop")["payload"], "borrower_pseudonym": f"COOP-{unique('E')[:8]}"}
    created = gateway.post("/api/v1/finance/applications", headers=analyst, json=payload)
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    assert created.json()["status"] == "DRAFT"

    for doc_type in ("farm_business_plan", "yield_or_sales_evidence", "land_use_evidence"):
        body = f"---\ntitle: {doc_type}\n---\n## Evidence\nSynthetic {doc_type.replace('_', ' ')} for rice harvest yield of 4 tonnes per hectare."
        r = gateway.post(f"/api/v1/finance/applications/{aid}/documents", headers=analyst,
                         files={"file": (f"{doc_type}.md", BytesIO(body.encode()), "text/markdown")}, data={"document_type": doc_type})
        assert r.status_code == 201, r.text

    assert gateway.post(f"/api/v1/finance/applications/{aid}/review", headers=analyst, json={"action": "submit"}).json()["status"] == "SUBMITTED"
    analysis = gateway.post(f"/api/v1/finance/applications/{aid}/analyze", headers=analyst, json={}).json()
    assert "MISSING_SUPPORTING_DOCUMENTATION" not in {f["code"] for f in analysis["flags"]}
    sim = gateway.post(f"/api/v1/finance/applications/{aid}/simulate", headers=analyst,
                       json={"scenarios": [{"name": "yield -20 and price -15", "yield_change_pct": -20, "price_change_pct": -15}]}).json()
    assert sim["results"][1]["summary"]["repayment_coverage_ratio"] == "0.925"
    assert gateway.post(f"/api/v1/finance/applications/{aid}/review", headers=analyst, json={"action": "start_review"}).json()["status"] == "IN_REVIEW"
    decision = gateway.post(f"/api/v1/finance/applications/{aid}/review", headers=reviewer,
                            json={"action": "approve", "reason": "Coverage 1.456 at baseline; combined shock risk accepted with storage plan",
                                  "evidence_refs": [f"analysis:{analysis['id']}"]})
    assert decision.status_code == 200 and decision.json()["status"] == "APPROVED"
    assert decision.json()["recorded_by"] == "kofi.credit"

    audit = gateway.get(f"/api/v1/finance/applications/{aid}/audit", headers=analyst).json()
    states = [d["to_state"] for d in audit["decisions"]]
    assert states == ["SUBMITTED", "ANALYZED", "IN_REVIEW", "APPROVED"]
    final = audit["decisions"][-1]
    assert final["actor_kind"] == "human" and final["evidence_refs"] and final["versions"]["rules"].startswith("finance-risk-rules")


def test_project_milestones_documents_brief_review(gateway, db_session):
    pid = str(find_project(db_session, "DEMO-IRR-01").id)
    analyst, reviewer = auth("ana.project"), auth("rita.reviewer")
    before = gateway.get(f"/api/v1/projects/{pid}/reports", headers=analyst).json()
    assert {m["period"] for m in before["missing"]} == {"2025-Q4", "2025-H2"}

    report = b"---\ntitle: Quarterly Progress Report 2025-Q4\n---\n## Progress\nPhase one construction reached 30 percent in December 2025."
    up = gateway.post(f"/api/v1/projects/{pid}/documents", headers=analyst,
                      files={"file": ("q4.md", BytesIO(report), "text/markdown")},
                      data={"document_type": "progress_report", "reporting_period": "2025-Q4", "report_type": "quarterly_progress"})
    assert up.status_code == 201 and up.json()["links"]["report"] == "quarterly_progress 2025-Q4"
    after = gateway.get(f"/api/v1/projects/{pid}/reports", headers=analyst).json()
    assert {m["period"] for m in after["missing"]} == {"2025-H2"}

    brief = gateway.post(f"/api/v1/projects/{pid}/brief", headers=analyst)
    assert brief.status_code == 201, brief.text
    b = brief.json()
    assert b["status"] == "DRAFT" and b["citations"]
    assert "42.0%" in b["narrative"] and "60.0%" in b["narrative"]
    assert b["sections"]["progress_summary"]["gap_pp"] == "18.0"
    assert gateway.post(f"/api/v1/projects/{pid}/review", headers=analyst, json={"brief_id": b["id"], "action": "submit"}).json()["status"] == "SUBMITTED"
    ok = gateway.post(f"/api/v1/projects/{pid}/review", headers=reviewer,
                      json={"brief_id": b["id"], "action": "approve", "reason": "Figures checked against the supervision report",
                            "evidence_refs": [c["chunk_reference"] for c in b["citations"][:2]]})
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    audit = gateway.get(f"/api/v1/projects/{pid}/audit", headers=analyst).json()
    assert [d["to_state"] for d in audit["decisions"]][-2:] == ["SUBMITTED", "APPROVED"]
