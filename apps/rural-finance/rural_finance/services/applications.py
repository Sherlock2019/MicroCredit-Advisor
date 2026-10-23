"""Application persistence, analysis orchestration and scenario simulation."""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from ifad_audit import append_audit_event
from ifad_common.errors import DomainError
from ifad_common.security.principal import Principal
from ifad_credit_adapter import CreditPolicyAdapter
from ifad_rag.models import Document, document_summary
from ifad_review import FINANCE_WORKFLOW, record_transition
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rural_finance.models import Analysis, CostLineRow, CropPlanRow, LoanApplication
from rural_finance.schemas import ApplicationCreate, ScenarioIn
from rural_finance.services import briefing
from rural_finance.services.cashflow import (
    ENGINE_VERSION,
    STANDARD_SCENARIOS,
    CostLine,
    CropPlan,
    FarmCashFlowInput,
    LoanTerms,
    Scenario,
    assumptions,
    project_cash_flow,
)
from rural_finance.services.risk_flags import evaluate_flags, rules

ANALYZABLE = {"SUBMITTED", "ANALYZED"}
LOCKED = {"IN_REVIEW", "APPROVED", "DECLINED"}


def get_application(db: Session, application_id: uuid.UUID) -> LoanApplication:
    app = db.execute(select(LoanApplication).options(selectinload(LoanApplication.crops), selectinload(LoanApplication.costs))
                     .where(LoanApplication.id == application_id)).scalar_one_or_none()
    if app is None:
        raise DomainError("Application not found", 404)
    return app


def create_application(db: Session, principal: Principal, payload: ApplicationCreate, *, synthetic: bool = True) -> LoanApplication:
    data = payload.model_dump(exclude={"crops", "costs"})
    app = LoanApplication(tenant_id=principal.tenant_id, reference=f"RF-{payload.start_month.year}-{uuid.uuid4().hex[:6].upper()}",
                          status="DRAFT", synthetic=synthetic, created_by=principal.actor, **data)
    app.crops = [CropPlanRow(**c.model_dump()) for c in payload.crops]
    app.costs = [CostLineRow(**c.model_dump()) for c in payload.costs]
    db.add(app)
    db.flush()
    append_audit_event(db, principal, "loan_application.created", subject_type="loan_application", subject_id=str(app.id),
                       details={"reference": app.reference, "requested_amount": str(app.requested_amount),
                                "currency": app.currency, "synthetic": synthetic})
    return app


def to_engine_input(app: LoanApplication) -> FarmCashFlowInput:
    return FarmCashFlowInput(
        currency=app.currency, start_month=app.start_month,
        crops=tuple(CropPlan(c.crop, c.area_ha, c.expected_yield_t_per_ha, c.price_per_t, c.harvest_month, c.sale_share, c.yield_basis)
                    for c in app.crops),
        costs=tuple(CostLine(c.category, c.amount, c.month, c.kind) for c in app.costs),
        loan=LoanTerms(app.requested_amount, app.annual_interest_rate_pct, app.term_months, app.repayment_type,
                       tuple(app.repayment_months or ())),
        other_monthly_income=app.other_monthly_income, operating_expenses_monthly=app.operating_expenses_monthly,
        existing_obligations_monthly=app.existing_obligations_monthly, opening_cash_balance=app.opening_cash_balance,
    )


def input_digest(data: FarmCashFlowInput) -> str:
    return hashlib.sha256(json.dumps(data, default=lambda o: o.__dict__ if hasattr(o, "__dict__") else str(o),
                                     sort_keys=True).encode()).hexdigest()


def document_types(db: Session, app: LoanApplication) -> set[str]:
    rows = db.execute(select(Document.document_type).where(Document.tenant_id == app.tenant_id, Document.domain == "finance",
                                                           Document.scope_id == app.id)).scalars()
    return set(rows)


def list_documents(db: Session, app: LoanApplication) -> list[dict]:
    docs = db.execute(select(Document).where(Document.tenant_id == app.tenant_id, Document.domain == "finance",
                                             Document.scope_id == app.id).order_by(Document.created_at)).scalars()
    return [document_summary(d) for d in docs]


def _run_engine(data: FarmCashFlowInput, scenarios: tuple[Scenario, ...]) -> dict:
    try:
        return {s.name: project_cash_flow(data, s) for s in scenarios}
    except ValueError as exc:
        raise DomainError(f"Application data cannot be projected: {exc}", 422) from exc


def indicators(app: LoanApplication, baseline_summary: dict, data: FarmCashFlowInput) -> dict:
    adapter = CreditPolicyAdapter()
    out = {"obligation_burden": adapter.obligation_burden(baseline_summary["average_monthly_debt_service"],
                                                          baseline_summary["average_monthly_income"])}
    if app.repayment_type == "equal_monthly":
        from rural_finance.services.cashflow import amortised_payment

        ours = amortised_payment(data.loan.amount, data.loan.annual_rate_pct, data.loan.term_months)
        theirs = adapter.amortised_monthly_payment(data.loan.amount, data.loan.annual_rate_pct, data.loan.term_months)
        out["amortisation_cross_check"] = {"engine": str(ours), "banking_copilot": str(theirs), "agree": abs(ours - theirs) <= Decimal("0.01")}
    return out


def analyze(db: Session, principal: Principal, app: LoanApplication, explain: bool = True) -> Analysis:
    if app.status not in ANALYZABLE:
        raise DomainError(f"Analysis runs on SUBMITTED or ANALYZED applications; this one is {app.status}", 409)
    data = to_engine_input(app)
    results = _run_engine(data, STANDARD_SCENARIOS)
    flags = evaluate_flags(data, results, document_types(db, app), app.declared_annual_revenue, app.declared_production_costs)
    baseline = results["baseline"].as_dict()
    scenario_dicts = {k: v.as_dict() for k, v in results.items() if k != "baseline"}
    explanation = briefing.explain(db, principal, app.id, app.reference, app.currency, app.term_months, baseline,
                                   scenario_dicts, flags, use_model=explain)
    version = (db.execute(select(func.max(Analysis.version)).where(Analysis.application_id == app.id)).scalar() or 0) + 1
    analysis = Analysis(
        application_id=app.id, tenant_id=app.tenant_id, version=version, input_sha256=input_digest(data),
        engine_version=ENGINE_VERSION, rule_version=rules()["version"], adapter_version=CreditPolicyAdapter.version,
        baseline=json.loads(json.dumps(baseline, default=str)),
        scenarios=json.loads(json.dumps(list(scenario_dicts.values()), default=str)),
        flags=json.loads(json.dumps(flags, default=str)),
        indicators=json.loads(json.dumps(indicators(app, results["baseline"].summary, data), default=str)),
        assumptions=assumptions(data), explanation=explanation["text"],
        explanation_grounding=json.loads(json.dumps({**explanation["grounding"],
                                                     "excluded_flagged_chunks": explanation["excluded_flagged_chunks"]}, default=str)),
        citations=explanation["citations"], model_provider=explanation["provider"], model_name=explanation["model"],
        prompt_version=explanation["prompt_version"], created_by=principal.actor,
    )
    db.add(analysis)
    previous = app.status
    record_transition(db, principal, FINANCE_WORKFLOW, subject_id=app.id, created_by=app.created_by, from_state=previous,
                      to_state="ANALYZED", reason=f"analysis v{version}",
                      versions={"engine": ENGINE_VERSION, "rules": rules()["version"], "model": explanation["model"]})
    app.status = "ANALYZED"
    db.flush()
    append_audit_event(db, principal, "loan_application.analyzed", subject_type="loan_application", subject_id=str(app.id),
                       details={"analysis_id": str(analysis.id), "version": version, "flags": [f["code"] for f in flags],
                                "engine": ENGINE_VERSION, "rules": rules()["version"], "model": explanation["model"],
                                "explanation_grounding": explanation["grounding"].get("mode")})
    return analysis


def simulate(db: Session, principal: Principal, app: LoanApplication, specs: list[ScenarioIn], include_baseline: bool) -> dict:
    scenarios = tuple(Scenario(s.name, s.yield_change_pct, s.price_change_pct, s.input_cost_change_pct, s.harvest_delay_months)
                      for s in specs)
    if include_baseline:
        scenarios = (STANDARD_SCENARIOS[0], *scenarios)
    data = to_engine_input(app)
    results = _run_engine(data, scenarios)
    append_audit_event(db, principal, "loan_application.simulated", subject_type="loan_application", subject_id=str(app.id),
                       details={"scenarios": [s.label for s in scenarios], "engine": ENGINE_VERSION})
    return {"application_id": str(app.id), "engine_version": ENGINE_VERSION, "currency": app.currency,
            "assumptions": assumptions(data), "results": [r.as_dict() for r in results.values()]}


def latest_analysis(db: Session, app: LoanApplication) -> Analysis | None:
    return db.execute(select(Analysis).where(Analysis.application_id == app.id).order_by(Analysis.version.desc()).limit(1)).scalar_one_or_none()


def analysis_to_dict(a: Analysis) -> dict:
    return {"id": str(a.id), "application_id": str(a.application_id), "version": a.version, "input_sha256": a.input_sha256,
            "engine_version": a.engine_version, "rule_version": a.rule_version, "adapter_version": a.adapter_version,
            "baseline": a.baseline, "scenarios": a.scenarios, "flags": a.flags, "indicators": a.indicators,
            "assumptions": a.assumptions, "explanation": a.explanation, "explanation_grounding": a.explanation_grounding,
            "citations": a.citations, "model_provider": a.model_provider, "model_name": a.model_name,
            "prompt_version": a.prompt_version, "created_by": a.created_by, "created_at": a.created_at.isoformat(),
            "advisory_notice": "Advisory analysis only. Approval or decline is recorded by an authorised human reviewer."}


def transition(db: Session, principal: Principal, app: LoanApplication, to_state: str, reason: str | None,
               evidence_refs: list[str]) -> dict:
    versions: dict = {"workflow": FINANCE_WORKFLOW.name}
    if to_state in FINANCE_WORKFLOW.final_states:
        latest = latest_analysis(db, app)
        if latest is None:
            raise DomainError("Record an analysis before a final decision", 409)
        versions.update({"analysis_id": str(latest.id), "analysis_version": latest.version, "engine": latest.engine_version,
                         "rules": latest.rule_version, "model": latest.model_name, "prompt": latest.prompt_version})
    decision = record_transition(db, principal, FINANCE_WORKFLOW, subject_id=app.id, created_by=app.created_by,
                                 from_state=app.status, to_state=to_state, reason=reason, evidence_refs=evidence_refs,
                                 versions=versions)
    app.status = to_state
    db.flush()
    return {"application_id": str(app.id), "previous_state": decision.from_state, "status": app.status,
            "decision_id": str(decision.id), "recorded_by": decision.actor, "audit_event_id": decision.audit_event_id,
            "allowed_next": FINANCE_WORKFLOW.allowed(app.status)}
