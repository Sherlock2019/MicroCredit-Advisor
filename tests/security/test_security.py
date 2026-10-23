"""Security controls: authentication, roles, tenant/project isolation, agent limits, prompt injection."""
import time

import jwt
import pytest
from ifad_common.config import get_settings

from tests.conftest import auth, find_application, find_project

pytestmark = pytest.mark.security


def _token(**claims):
    s = get_settings()
    now = int(time.time())
    base = {"iss": s.auth_dev_issuer, "aud": s.oidc_audience, "sub": "dev|x", "roles": ["finance_reviewer"],
            "tenant_id": "tenant-demo-a", "iat": now, "exp": now + 600}
    base.update(claims)
    return {"Authorization": "Bearer " + jwt.encode(base, s.auth_dev_jwt_secret, algorithm="HS256")}


def test_missing_expired_forged_and_wrong_audience_tokens_rejected(gateway):
    url = "/api/v1/finance/applications"
    assert gateway.get(url).status_code == 401
    assert gateway.get(url, headers=_token(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200)).status_code == 401
    assert gateway.get(url, headers=_token(aud="someone-else")).status_code == 401
    forged = jwt.encode({"iss": get_settings().auth_dev_issuer, "aud": get_settings().oidc_audience, "sub": "x", "roles": ["finance_reviewer"],
                         "tenant_id": "tenant-demo-a", "iat": int(time.time()), "exp": int(time.time()) + 60}, "wrong-secret-" * 4, algorithm="HS256")
    assert gateway.get(url, headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_analyst_cannot_approve_and_denial_is_audited(gateway, db_session):
    app = find_application(db_session, "BRW-BD5520")  # IN_REVIEW
    r = gateway.post(f"/api/v1/finance/applications/{app.id}/review", headers=auth("fatima.finance"),
                     json={"action": "approve", "reason": "looks fine", "evidence_refs": ["x"]})
    assert r.status_code == 403
    events = gateway.get("/api/v1/audit/events?event_type=access.denied&limit=50", headers=auth("aude.auditor")).json()["items"]
    assert any(e["actor"] == "fatima.finance" for e in events)


def test_final_decision_needs_reason_evidence_and_segregation(gateway, db_session):
    app = find_application(db_session, "BRW-BD5520")
    url = f"/api/v1/finance/applications/{app.id}/review"
    assert gateway.post(url, headers=auth("kofi.credit"), json={"action": "approve", "evidence_refs": ["x"]}).status_code == 422
    assert gateway.post(url, headers=auth("kofi.credit"), json={"action": "approve", "reason": "ok"}).status_code == 422
    # The analyst who created it, even if also given the reviewer role, may not decide it.
    both = auth("fatima.finance", roles=["finance_analyst", "finance_reviewer"])
    r = gateway.post(url, headers=both, json={"action": "approve", "reason": "self", "evidence_refs": ["x"]})
    assert r.status_code == 403 and "Segregation" in r.json()["error"]["message"]


def test_cross_tenant_access_rejected(gateway, db_session):
    tenant_b_app = find_application(db_session, "BRW-MG3001")
    assert gateway.get(f"/api/v1/finance/applications/{tenant_b_app.id}", headers=auth("fatima.finance")).status_code == 403
    a_app = find_application(db_session, "COOP-A0001")
    assert gateway.get(f"/api/v1/finance/applications/{a_app.id}", headers=auth("bea.tenantb")).status_code == 403
    tenant_b_project = find_project(db_session, "DEMO-AQUA-08")
    assert gateway.get(f"/api/v1/projects/{tenant_b_project.id}", headers=auth("ana.project")).status_code == 403


def test_cross_project_read_rejected(gateway, db_session):
    irr = find_project(db_session, "DEMO-IRR-01")
    mkt = find_project(db_session, "DEMO-MKT-02")
    assert gateway.get(f"/api/v1/projects/{mkt.id}", headers=auth("omar.project")).status_code == 200
    assert gateway.get(f"/api/v1/projects/{irr.id}", headers=auth("omar.project")).status_code == 403
    r = gateway.post("/api/v1/knowledge/query", headers=auth("omar.project"),
                     json={"question": "causes of construction delay", "scopes": [{"domain": "project", "id": str(irr.id)}]})
    assert r.status_code == 403


def test_documents_never_cross_tenant_in_retrieval(gateway, db_session):
    a_app = find_application(db_session, "COOP-A0001")
    ans = gateway.post(f"/api/v1/finance/applications/{a_app.id}/ask", headers=auth("fatima.finance"),
                       json={"question": "rice near Lake Alaotra confidential to tenant B"}).json()
    assert all("Tenant B" not in c["title"] for c in ans["citations"])


def test_agent_token_can_analyze_but_never_decide(gateway, db_session):
    app = find_application(db_session, "BRW-UG7731")
    run = gateway.post("/api/v1/agents/runs", headers=auth("fatima.finance"),
                       json={"agent_id": "finance-briefing-agent", "scope_id": str(app.id)}).json()
    agent = {"Authorization": f"Bearer {run['access_token']}"}
    assert gateway.post(f"/api/v1/finance/applications/{app.id}/analyze", headers=agent, json={"explain": False}).status_code == 200
    r = gateway.post(f"/api/v1/finance/applications/{app.id}/review", headers=agent,
                     json={"action": "approve", "reason": "the model says so", "evidence_refs": ["x"]})
    assert r.status_code == 403
    other = find_application(db_session, "COOP-A0001")
    assert gateway.get(f"/api/v1/finance/applications/{other.id}", headers=agent).status_code == 403
    assert gateway.post("/api/v1/agents/runs", headers=agent,
                        json={"agent_id": "finance-briefing-agent", "scope_id": str(app.id)}).status_code == 403


def test_prompt_injection_is_flagged_excluded_and_cannot_change_state(gateway, db_session):
    app = find_application(db_session, "BRW-UG7731")
    before = gateway.get(f"/api/v1/finance/applications/{app.id}", headers=auth("fatima.finance")).json()
    assert any("contains_instruction_like_text" in d["flags"] for d in before["documents"])
    ans = gateway.post(f"/api/v1/finance/applications/{app.id}/ask", headers=auth("fatima.finance"),
                       json={"question": "What does the note added by the applicant say about approving the loan?"}).json()
    assert ans["excluded_flagged"] and "approve this loan" not in ans["answer"].lower()
    after = gateway.get(f"/api/v1/finance/applications/{app.id}", headers=auth("fatima.finance")).json()
    assert after["status"] == before["status"]
