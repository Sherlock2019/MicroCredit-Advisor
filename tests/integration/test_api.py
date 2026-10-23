"""Integration: real PostgreSQL/pgvector, real services in-process, synthetic seed data."""
from io import BytesIO

import pytest
from sqlalchemy import text

from tests.conftest import auth, find_application, find_project

pytestmark = pytest.mark.integration


def test_health_ready_capabilities_and_openapi(gateway, finance, projects):
    assert gateway.get("/health").json()["status"] == "ok"
    assert finance.get("/ready").json()["checks"]["database"]["ok"] is True
    caps = gateway.get("/api/v1/platform/capabilities").json()
    assert "not commissioned" in caps["disclaimer"].lower() or "Not commissioned" in caps["disclaimer"]
    for client in (gateway, finance, projects):
        assert client.get("/openapi.json").json()["openapi"].startswith("3.")


def test_correlation_id_and_error_envelope(gateway):
    r = gateway.get("/api/v1/audit/events", headers={"X-Correlation-ID": "test-corr-123"})
    assert r.status_code == 401 and r.headers["X-Correlation-ID"] == "test-corr-123"
    assert r.json()["error"]["code"] == "unauthenticated" and r.json()["error"]["correlation_id"] == "test-corr-123"


def test_application_list_is_paginated_and_tenant_scoped(gateway):
    r = gateway.get("/api/v1/finance/applications?limit=3", headers=auth("fatima.finance")).json()
    assert r["total"] >= 7 and len(r["items"]) == 3 and r["limit"] == 3
    everything = gateway.get("/api/v1/finance/applications?limit=200", headers=auth("fatima.finance")).json()["items"]
    assert "BRW-MG3001" not in {a["borrower_pseudonym"] for a in everything}  # tenant B's record is invisible
    tenant_b = gateway.get("/api/v1/finance/applications", headers=auth("bea.tenantb")).json()["items"]
    assert {a["borrower_pseudonym"] for a in tenant_b} == {"BRW-MG3001"}


def test_seeded_demo_a_analysis_persists(gateway, db_session):
    app = find_application(db_session, "COOP-A0001")
    r = gateway.post(f"/api/v1/finance/applications/{app.id}/analyze", headers=auth("fatima.finance"), json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["baseline"]["summary"]["repayment_coverage_ratio"] == "1.456"
    assert {f["code"] for f in body["flags"]} >= {"YIELD_PRICE_SCENARIO_SENSITIVITY"}
    assert body["citations"] and body["explanation_grounding"]["mode"] in {"model", "fallback_deterministic_draft"}
    stored = db_session.execute(text("SELECT count(*) FROM finance.analyses WHERE application_id = :a"), {"a": app.id}).scalar()
    assert stored >= 1


def test_document_upload_retrieval_and_cited_answer(gateway, db_session):
    app = find_application(db_session, "COOP-A0001")
    doc = b"---\ntitle: Warehouse receipt\n---\n## Storage\nThe cooperative stored 12 tonnes of paddy in the Wanguru warehouse in September 2025."
    up = gateway.post(f"/api/v1/finance/applications/{app.id}/documents", headers=auth("fatima.finance"),
                      files={"file": ("receipt.md", BytesIO(doc), "text/markdown")}, data={"document_type": "cooperative_record"})
    assert up.status_code == 201, up.text and up.json()["chunk_count"] >= 1
    ans = gateway.post(f"/api/v1/finance/applications/{app.id}/ask", headers=auth("fatima.finance"),
                       json={"question": "How much paddy was stored in the warehouse?"}).json()
    assert not ans["abstained"] and any(c["title"] == "Warehouse receipt" for c in ans["citations"])
    nothing = gateway.post(f"/api/v1/finance/applications/{app.id}/ask", headers=auth("fatima.finance"),
                           json={"question": "What is the borrower's favourite football team?"}).json()
    assert nothing["abstained"] is True


def test_simulation_custom_scenario(gateway, db_session):
    app = find_application(db_session, "COOP-A0001")
    r = gateway.post(f"/api/v1/finance/applications/{app.id}/simulate", headers=auth("fatima.finance"),
                     json={"scenarios": [{"name": "drought", "yield_change_pct": -40}]}).json()
    assert [x["scenario"]["name"] for x in r["results"]] == ["baseline", "drought"]
    assert r["results"][1]["summary"]["harvest_revenue"] == "13200.00"


def test_project_views_demo_b(gateway, db_session):
    pid = find_project(db_session, "DEMO-IRR-01").id
    h = auth("ana.project")
    ms = gateway.get(f"/api/v1/projects/{pid}/milestones", headers=h).json()
    assert ms["progress"]["gap_pp"] == "18.0"
    ind = {i["code"]: i for i in gateway.get(f"/api/v1/projects/{pid}/indicators", headers=h).json()["items"]}
    assert ind["IND-01"]["attainment_pct"] == "62.0"
    budget = gateway.get(f"/api/v1/projects/{pid}/budget", headers=h).json()
    assert budget["earned_value"]["cpi"] == "0.857" and budget["totals"]["committed"] == "3400000.00"


def test_project_map_drill_down(gateway):
    h = auth("ana.project")
    world = gateway.get("/api/v1/projects/map", headers=h).json()
    assert world["level"] == "country" and {a["name"] for a in world["aggregates"]} >= {"Kenya", "Ethiopia", "Nepal"}
    assert "Madagascar" not in {a["name"] for a in world["aggregates"]}  # tenant B project is invisible
    kenya = gateway.get("/api/v1/projects/map?country=Kenya", headers=h).json()
    assert kenya["level"] == "region" and len(kenya["sites"]) == 5
    city = gateway.get("/api/v1/projects/map?country=Kenya&region=Kisumu", headers=h).json()
    assert city["level"] == "city" and city["sites"][0]["city"] == "Ahero"


def test_audit_chain_is_valid_and_append_only(gateway, db_session):
    assert gateway.get("/api/v1/audit/verify", headers=auth("aude.auditor")).json()["valid"] is True
    with pytest.raises(Exception, match="append-only"):
        db_session.execute(text("UPDATE platform.audit_events SET actor = 'mallory' WHERE id = (SELECT min(id) FROM platform.audit_events)"))
