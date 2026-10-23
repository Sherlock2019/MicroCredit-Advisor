"""/api/v1/finance — Rural Finance Copilot API. Every route authenticates and authorizes server-side."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from ifad_audit import append_audit_event
from ifad_audit.models import AuditEvent, audit_to_dict
from ifad_common.access import ensure_application_access
from ifad_common.db import get_db
from ifad_common.errors import DomainError
from ifad_common.pagination import Page, PageParams, page_params
from ifad_common.security.dependencies import forbid, require_permission
from ifad_common.security.principal import Principal
from ifad_rag import Scope, answer_question, ingest_document
from ifad_rag.models import document_summary
from ifad_review import FINANCE_WORKFLOW, TransitionError
from ifad_review.models import ReviewDecision, decision_to_dict
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from rural_finance.models import LoanApplication
from rural_finance.schemas import (
    ACTION_TO_STATE,
    AnalyzeRequest,
    ApplicationCreate,
    ApplicationOut,
    ApplicationSummary,
    AskRequest,
    ReviewRequest,
    SimulateRequest,
)
from rural_finance.services import applications as svc

router = APIRouter(prefix="/api/v1/finance", tags=["rural-finance"])
FinanceDocType = Literal["farm_business_plan", "yield_or_sales_evidence", "land_use_evidence", "cooperative_record",
                         "input_quotation", "other_evidence"]


def _summary(app: LoanApplication) -> dict:
    return {"id": str(app.id), "reference": app.reference, "borrower_pseudonym": app.borrower_pseudonym,
            "borrower_type": app.borrower_type, "group_name": app.group_name, "country": app.country, "region": app.region,
            "locality": app.locality, "currency": app.currency, "requested_amount": app.requested_amount, "status": app.status,
            "synthetic": app.synthetic, "primary_crop": app.crops[0].crop if app.crops else None, "created_by": app.created_by,
            "updated_at": app.updated_at}


def _detail(db: Session, app: LoanApplication) -> dict:
    latest = svc.latest_analysis(db, app)
    return {**_summary(app),
            **{k: getattr(app, k) for k in ("cultivated_area_ha", "loan_purpose", "annual_interest_rate_pct", "term_months",
                                            "start_month", "repayment_type", "repayment_months", "other_monthly_income",
                                            "operating_expenses_monthly", "existing_obligations_monthly", "opening_cash_balance",
                                            "declared_annual_revenue", "declared_production_costs", "latitude", "longitude")},
            "crops": [{"crop": c.crop, "area_ha": c.area_ha, "expected_yield_t_per_ha": c.expected_yield_t_per_ha,
                       "yield_basis": c.yield_basis, "price_per_t": c.price_per_t, "harvest_month": c.harvest_month,
                       "sale_share": c.sale_share} for c in app.crops],
            "costs": [{"category": c.category, "kind": c.kind, "amount": c.amount, "month": c.month} for c in app.costs],
            "allowed_transitions": FINANCE_WORKFLOW.allowed(app.status), "documents": svc.list_documents(db, app),
            "latest_analysis_id": str(latest.id) if latest else None}


def _load(db: Session, principal: Principal, application_id: str, request: Request) -> LoanApplication:
    aid = ensure_application_access(db, principal, application_id, request)
    return svc.get_application(db, aid)


@router.get("/applications", response_model=Page[ApplicationSummary], summary="List loan applications in your tenant")
def list_applications(page: PageParams = Depends(page_params), status_filter: str | None = Query(None, alias="status"),
                      country: str | None = None, principal: Principal = Depends(require_permission("finance:read")),
                      db: Session = Depends(get_db)):
    stmt = select(LoanApplication).where(LoanApplication.tenant_id == principal.tenant_id)
    if principal.is_agent:
        stmt = stmt.where(LoanApplication.id == principal.scope_id)
    if status_filter:
        stmt = stmt.where(LoanApplication.status == status_filter)
    if country:
        stmt = stmt.where(LoanApplication.country == country)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.options(selectinload(LoanApplication.crops)).order_by(LoanApplication.created_at.desc())
                      .limit(page.limit).offset(page.offset)).scalars().all()
    return {"items": [_summary(a) for a in rows], "total": total, "limit": page.limit, "offset": page.offset}


@router.post("/applications", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED,
             summary="Create a loan application (DRAFT)")
def create_application(payload: ApplicationCreate, principal: Principal = Depends(require_permission("finance:create")),
                       db: Session = Depends(get_db)):
    app = svc.create_application(db, principal, payload)
    return _detail(db, svc.get_application(db, app.id))


@router.get("/applications/map", summary="Application locations (rounded to ~10 km) for the portfolio map")
def application_map(principal: Principal = Depends(require_permission("finance:read")), db: Session = Depends(get_db)):
    rows = db.execute(select(LoanApplication).options(selectinload(LoanApplication.crops))
                      .where(LoanApplication.tenant_id == principal.tenant_id, LoanApplication.latitude.is_not(None))).scalars()
    return {"precision_note": "Coordinates rounded to 0.1 degree to avoid locating individual farms.",
            "items": [{**_summary(a), "latitude": round(float(a.latitude), 1), "longitude": round(float(a.longitude), 1)}
                      for a in rows]}


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: str, request: Request, principal: Principal = Depends(require_permission("finance:read")),
                    db: Session = Depends(get_db)):
    return _detail(db, _load(db, principal, application_id, request))


@router.post("/applications/{application_id}/analyze",
             summary="Run the deterministic cash-flow analysis, risk flags and a cited explanation (advisory)")
def analyze_application(application_id: str, request: Request, body: AnalyzeRequest | None = None,
                        principal: Principal = Depends(require_permission("finance:analyze")), db: Session = Depends(get_db)):
    app = _load(db, principal, application_id, request)
    analysis = svc.analyze(db, principal, app, explain=(body or AnalyzeRequest()).explain)
    return svc.analysis_to_dict(analysis)


@router.get("/applications/{application_id}/analysis", summary="Latest stored analysis")
def get_analysis(application_id: str, request: Request, principal: Principal = Depends(require_permission("finance:read")),
                 db: Session = Depends(get_db)):
    app = _load(db, principal, application_id, request)
    latest = svc.latest_analysis(db, app)
    if latest is None:
        raise DomainError("No analysis yet", 404)
    return svc.analysis_to_dict(latest)


@router.post("/applications/{application_id}/simulate", summary="What-if yield / price / cost / harvest-delay scenarios")
def simulate(application_id: str, body: SimulateRequest, request: Request,
             principal: Principal = Depends(require_permission("finance:analyze")), db: Session = Depends(get_db)):
    app = _load(db, principal, application_id, request)
    return svc.simulate(db, principal, app, body.scenarios, body.include_baseline)


@router.post("/applications/{application_id}/documents", status_code=status.HTTP_201_CREATED,
             summary="Upload borrower evidence (PDF, DOCX, MD, TXT, CSV); indexed for cited retrieval")
async def upload_document(application_id: str, request: Request, file: UploadFile = File(...),
                          document_type: FinanceDocType = Form(...), title: str | None = Form(None, max_length=300),
                          principal: Principal = Depends(require_permission("finance:documents")),
                          db: Session = Depends(get_db)):
    data = await file.read()
    from starlette.concurrency import run_in_threadpool

    def _store():
        app = _load(db, principal, application_id, request)
        if app.status in svc.LOCKED:
            raise DomainError(f"Documents cannot be added while the application is {app.status}", 409)
        doc, created = ingest_document(db, principal, domain="finance", scope_id=app.id, filename=file.filename or "upload",
                                       data=data, document_type=document_type, title=title, provenance="synthetic" if app.synthetic else "uploaded")
        append_audit_event(db, principal, "document.ingested" if created else "document.duplicate", subject_type="loan_application",
                           subject_id=str(app.id), details={"document_id": str(doc.id), "document_type": document_type,
                                                            "sha256": doc.sha256, "chunks": doc.chunk_count, "flags": doc.flags})
        return {**document_summary(doc), "created": created}

    return await run_in_threadpool(_store)


@router.get("/applications/{application_id}/documents")
def list_documents(application_id: str, request: Request, principal: Principal = Depends(require_permission("finance:read")),
                   db: Session = Depends(get_db)):
    return {"items": svc.list_documents(db, _load(db, principal, application_id, request))}


@router.post("/applications/{application_id}/ask", summary="Ask a question answered only from this application's documents")
def ask(application_id: str, body: AskRequest, request: Request,
        principal: Principal = Depends(require_permission("knowledge:read")), db: Session = Depends(get_db)):
    if "finance:read" not in principal.permissions:
        raise forbid(principal, "Missing permission finance:read", request)
    app = _load(db, principal, application_id, request)
    answer = answer_question(db, principal, body.question, [Scope("finance", app.id)])
    append_audit_event(db, principal, "knowledge.queried", subject_type="loan_application", subject_id=str(app.id),
                       details={"question_chars": len(body.question), "abstained": answer.abstained,
                                "citations": [c["chunk_reference"] for c in answer.citations]})
    return answer.__dict__


@router.post("/applications/{application_id}/review",
             summary="Record a human workflow action. APPROVED/DECLINED require finance_reviewer, a reason and evidence")
def review(application_id: str, body: ReviewRequest, request: Request,
           principal: Principal = Depends(require_permission("finance:read")), db: Session = Depends(get_db)):
    app = _load(db, principal, application_id, request)
    try:
        return svc.transition(db, principal, app, ACTION_TO_STATE[body.action], body.reason, body.evidence_refs)
    except TransitionError as exc:
        if exc.status_code == 403:
            raise forbid(principal, str(exc), request, application_id=application_id, action=body.action) from exc
        raise


@router.get("/applications/{application_id}/audit", summary="Decision provenance: workflow decisions and audit events")
def application_audit(application_id: str, request: Request, principal: Principal = Depends(require_permission("finance:read")),
                      db: Session = Depends(get_db)):
    app = _load(db, principal, application_id, request)
    events = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == app.tenant_id, AuditEvent.subject_type == "loan_application",
                                                 AuditEvent.subject_id == str(app.id)).order_by(AuditEvent.id)).scalars()
    decisions = db.execute(select(ReviewDecision).where(ReviewDecision.subject_id == app.id).order_by(ReviewDecision.decided_at)).scalars()
    return {"application_id": str(app.id), "status": app.status, "decisions": [decision_to_dict(d) for d in decisions],
            "events": [audit_to_dict(e) for e in events]}
