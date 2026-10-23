"""/api/v1/projects — Project Monitoring & Impact Copilot API. Tenant + project-membership isolation on every route."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from ifad_audit import append_audit_event
from ifad_audit.models import AuditEvent, audit_to_dict
from ifad_common.access import accessible_project_ids, ensure_project_access
from ifad_common.db import get_db
from ifad_common.errors import DomainError
from ifad_common.pagination import Page, PageParams, page_params
from ifad_common.security.dependencies import forbid, require_permission
from ifad_common.security.principal import Principal
from ifad_rag import Scope, answer_question, ingest_document
from ifad_rag.models import Document, document_summary
from ifad_review import TransitionError
from ifad_review.models import ReviewDecision, decision_to_dict
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from project_impact.models import FieldReport, Indicator, Milestone, Project, ProjectBrief, ProjectMember, ProjectSite
from project_impact.schemas import BRIEF_ACTION_TO_STATE, AskRequest, BriefReviewRequest, ProjectCreate, ProjectSummary
from project_impact.services import monitoring as svc

router = APIRouter(prefix="/api/v1/projects", tags=["project-impact"])
ProjectDocType = Literal["progress_report", "supervision_report", "financial_report", "field_report", "evidence_record",
                         "design_document", "public_reference"]


def _summary(p: Project, site_count: int) -> dict:
    return {"id": str(p.id), "code": p.code, "name": p.name, "theme": p.theme, "country": p.country,
            "financing_amount": p.financing_amount, "currency": p.currency, "status": p.status, "start_date": p.start_date,
            "end_date": p.end_date, "reporting_as_of": p.reporting_as_of, "synthetic": p.synthetic, "site_count": site_count,
            "updated_at": p.updated_at}


def _load(db: Session, principal: Principal, project_id: str, request: Request) -> Project:
    return svc.get_project(db, ensure_project_access(db, principal, project_id, request))


@router.get("", response_model=Page[ProjectSummary], summary="Projects you are assigned to")
def list_projects(page: PageParams = Depends(page_params), country: str | None = None, theme: str | None = None,
                  principal: Principal = Depends(require_permission("project:read")), db: Session = Depends(get_db)):
    ids = accessible_project_ids(db, principal)
    stmt = select(Project).where(Project.tenant_id == principal.tenant_id, Project.id.in_(ids or [uuid.uuid4()]))
    if country:
        stmt = stmt.where(Project.country == country)
    if theme:
        stmt = stmt.where(Project.theme == theme)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Project.code).limit(page.limit).offset(page.offset)).scalars().all()
    counts = dict(db.execute(select(ProjectSite.project_id, func.count()).where(ProjectSite.project_id.in_([p.id for p in rows]))
                             .group_by(ProjectSite.project_id)).all())
    return {"items": [_summary(p, counts.get(p.id, 0)) for p in rows], "total": total, "limit": page.limit, "offset": page.offset}


@router.post("", status_code=status.HTTP_201_CREATED, summary="Register a project; the creator is assigned to it")
def create_project(payload: ProjectCreate, principal: Principal = Depends(require_permission("project:create")),
                   db: Session = Depends(get_db)):
    if db.execute(select(Project.id).where(Project.code == payload.code)).first():
        raise DomainError(f"Project code {payload.code} already exists", 409)
    project = Project(tenant_id=principal.tenant_id, created_by=principal.actor, synthetic=True,
                      **payload.model_dump(exclude={"sites"}))
    project.sites = [ProjectSite(**s.model_dump()) for s in payload.sites]
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, subject=principal.subject, project_role="project_analyst", added_by=principal.actor))
    append_audit_event(db, principal, "project.created", subject_type="project", subject_id=str(project.id),
                       details={"code": project.code, "financing_amount": str(project.financing_amount), "currency": project.currency})
    db.flush()
    return _summary(project, len(project.sites))


@router.get("/map", summary="Project sites by country / region / city with drill-down aggregates")
def project_map(country: str | None = Query(None, max_length=80), region: str | None = Query(None, max_length=120),
                city: str | None = Query(None, max_length=120), theme: str | None = Query(None, max_length=40),
                principal: Principal = Depends(require_permission("project:read")), db: Session = Depends(get_db)):
    return svc.map_view(db, accessible_project_ids(db, principal), country, region, city, theme)


@router.get("/{project_id}")
def get_project(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
                db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    latest = svc.latest_analysis(db, p)
    return {**_summary(p, len(p.sites)), "programme_name": p.programme_name, "objectives": p.objectives,
            "expected_results": p.expected_results, "baseline_summary": p.baseline_summary,
            "implementing_organization": p.implementing_organization, "created_by": p.created_by,
            "sites": [{"site_name": s.site_name, "region": s.region, "city": s.city, "latitude": float(s.latitude),
                       "longitude": float(s.longitude), "activity_type": s.activity_type,
                       "beneficiaries_target": s.beneficiaries_target, "beneficiaries_reached": s.beneficiaries_reached}
                      for s in p.sites],
            "latest_analysis_id": str(latest.id) if latest else None}


@router.get("/{project_id}/milestones")
def milestones(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
               db: Session = Depends(get_db)):
    from project_impact.services import calculations as calc

    p = _load(db, principal, project_id, request)
    ms = svc.milestone_inputs(db, p)
    rows = {m.activity_code: m for m in db.execute(select(Milestone).where(Milestone.project_id == p.id)).scalars()}
    items = []
    for m in ms:
        derived = calc.milestone_status(m, p.reporting_as_of)
        row = rows[m.code]
        items.append({**derived, "id": str(row.id), "planned_start": row.planned_start, "actual_start": row.actual_start,
                      "actual_end": row.actual_end, "evidence_document_id": str(row.evidence_document_id) if row.evidence_document_id else None,
                      "reviewer_comments": row.reviewer_comments})
    return {"as_of": p.reporting_as_of, "progress": calc.weighted_progress(ms), "items": items}


@router.get("/{project_id}/indicators")
def indicators(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
               db: Session = Depends(get_db)):
    from project_impact.services import calculations as calc

    p = _load(db, principal, project_id, request)
    progress = calc.weighted_progress(svc.milestone_inputs(db, p))
    return {"as_of": p.reporting_as_of, "expected_output_delivery_pct": progress["planned_pct"],
            "items": svc.indicator_view(db, p, progress["planned_pct"]),
            "levels": {"output": "goods and services delivered", "outcome": "changes among beneficiaries",
                       "impact": "long-term change; requires attribution analysis"}}


@router.get("/{project_id}/budget")
def budget(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
           db: Session = Depends(get_db)):
    from project_impact.services import calculations as calc

    p = _load(db, principal, project_id, request)
    return svc.budget_view(db, p, calc.weighted_progress(svc.milestone_inputs(db, p)))


@router.get("/{project_id}/reports")
def reports(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
            db: Session = Depends(get_db)):
    return svc.report_view(db, _load(db, principal, project_id, request))


@router.post("/{project_id}/documents", status_code=status.HTTP_201_CREATED,
             summary="Upload a field/supervision/progress report; optionally link it as milestone, indicator or report evidence")
async def upload_document(project_id: str, request: Request, file: UploadFile = File(...),
                          document_type: ProjectDocType = Form(...), title: str | None = Form(None, max_length=300),
                          reporting_period: str | None = Form(None, max_length=20),
                          source_url: str | None = Form(None, max_length=500), publication_date: date | None = Form(None),
                          license: str | None = Form(None, max_length=200),
                          milestone_code: str | None = Form(None, max_length=30),
                          indicator_code: str | None = Form(None, max_length=20),
                          report_type: str | None = Form(None, max_length=40),
                          principal: Principal = Depends(require_permission("project:documents")), db: Session = Depends(get_db)):
    data = await file.read()

    def _store():
        p = _load(db, principal, project_id, request)
        provenance = "public_reference" if document_type == "public_reference" else "synthetic" if p.synthetic else "uploaded"
        if provenance == "public_reference" and not (source_url and license):
            raise DomainError("Public reference documents need source_url and license (use terms) metadata", 422)
        doc, created = ingest_document(db, principal, domain="project", scope_id=p.id, filename=file.filename or "upload",
                                       data=data, document_type=document_type, title=title, provenance=provenance,
                                       metadata={"reporting_period": reporting_period, "source_url": source_url, "license": license,
                                                 "publication_date": publication_date.isoformat() if publication_date else None})
        links = {}
        if milestone_code:
            m = db.execute(select(Milestone).where(Milestone.project_id == p.id, Milestone.activity_code == milestone_code)).scalar_one_or_none()
            if m is None:
                raise DomainError(f"Unknown milestone {milestone_code}", 404)
            m.evidence_document_id, links["milestone"] = doc.id, milestone_code
        if indicator_code:
            i = db.execute(select(Indicator).where(Indicator.project_id == p.id, Indicator.code == indicator_code)).scalar_one_or_none()
            if i is None:
                raise DomainError(f"Unknown indicator {indicator_code}", 404)
            i.source_document_id, links["indicator"] = doc.id, indicator_code
        if report_type and reporting_period:
            r = db.execute(select(FieldReport).where(FieldReport.project_id == p.id, FieldReport.report_type == report_type,
                                                     FieldReport.period_label == reporting_period)).scalar_one_or_none()
            if r is None:
                raise DomainError(f"No expected {report_type} for {reporting_period}", 404)
            r.document_id, r.received_date, links["report"] = doc.id, date.today(), f"{report_type} {reporting_period}"
        append_audit_event(db, principal, "document.ingested" if created else "document.duplicate", subject_type="project",
                           subject_id=str(p.id), details={"document_id": str(doc.id), "document_type": document_type,
                                                          "sha256": doc.sha256, "chunks": doc.chunk_count, "links": links, "flags": doc.flags})
        return {**document_summary(doc), "created": created, "links": links}

    return await run_in_threadpool(_store)


@router.get("/{project_id}/documents")
def list_documents(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
                   db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    docs = db.execute(select(Document).where(Document.tenant_id == p.tenant_id, Document.domain == "project",
                                             Document.scope_id == p.id).order_by(Document.created_at)).scalars()
    return {"items": [document_summary(d) for d in docs]}


@router.post("/{project_id}/analyze", summary="Rule-based delay, evidence, budget and indicator checks")
def analyze(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:analyze")),
            db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    row = svc.analyze(db, principal, p)
    return {"analysis_id": str(row.id), "version": row.version, **row.results}


@router.post("/{project_id}/brief", status_code=status.HTTP_201_CREATED, summary="Generate an evidence-backed draft brief (DRAFT)")
def brief(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:brief")),
          db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    return svc.brief_to_dict(svc.generate_brief(db, principal, p))


@router.get("/{project_id}/briefs")
def list_briefs(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
                db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    rows = db.execute(select(ProjectBrief).where(ProjectBrief.project_id == p.id).order_by(ProjectBrief.version.desc())).scalars()
    return {"items": [svc.brief_to_dict(b) for b in rows]}


@router.post("/{project_id}/review", summary="Submit a brief for review, request changes, or approve (project_reviewer)")
def review(project_id: str, body: BriefReviewRequest, request: Request,
           principal: Principal = Depends(require_permission("project:read")), db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    try:
        brief_id = uuid.UUID(body.brief_id)
    except ValueError as exc:
        raise DomainError("brief_id must be a UUID", 422) from exc
    try:
        return svc.transition_brief(db, principal, p, brief_id, BRIEF_ACTION_TO_STATE[body.action], body.reason, body.evidence_refs)
    except TransitionError as exc:
        if exc.status_code == 403:
            raise forbid(principal, str(exc), request, project_id=project_id, action=body.action) from exc
        raise


@router.post("/{project_id}/ask", summary="Question answered only from this project's documents, with citations")
def ask(project_id: str, body: AskRequest, request: Request, principal: Principal = Depends(require_permission("knowledge:read")),
        db: Session = Depends(get_db)):
    if "project:read" not in principal.permissions:
        raise forbid(principal, "Missing permission project:read", request)
    p = _load(db, principal, project_id, request)
    answer = answer_question(db, principal, body.question, [Scope("project", p.id)])
    append_audit_event(db, principal, "knowledge.queried", subject_type="project", subject_id=str(p.id),
                       details={"question_chars": len(body.question), "abstained": answer.abstained,
                                "citations": [c["chunk_reference"] for c in answer.citations]})
    return answer.__dict__


@router.get("/{project_id}/audit")
def project_audit(project_id: str, request: Request, principal: Principal = Depends(require_permission("project:read")),
                  db: Session = Depends(get_db)):
    p = _load(db, principal, project_id, request)
    events = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == p.tenant_id, AuditEvent.subject_type == "project",
                                                 AuditEvent.subject_id == str(p.id)).order_by(AuditEvent.id)).scalars()
    brief_ids = list(db.execute(select(ProjectBrief.id).where(ProjectBrief.project_id == p.id)).scalars())
    decisions = db.execute(select(ReviewDecision).where(ReviewDecision.subject_id.in_(brief_ids or [uuid.uuid4()]))
                           .order_by(ReviewDecision.decided_at)).scalars()
    return {"project_id": str(p.id), "decisions": [decision_to_dict(d) for d in decisions], "events": [audit_to_dict(e) for e in events]}
