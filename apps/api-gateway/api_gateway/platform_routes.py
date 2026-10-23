"""Platform API hosted by the gateway: capabilities, operations status, knowledge, evaluations, audit, identities."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from ifad_audit import append_audit_event, verify_chain
from ifad_audit.models import AuditEvent, audit_to_dict
from ifad_common import metrics
from ifad_common.access import ensure_application_access, ensure_project_access
from ifad_common.app_factory import build_info
from ifad_common.config import get_settings
from ifad_common.correlation import outbound_headers
from ifad_common.db import get_db
from ifad_common.errors import DomainError
from ifad_common.pagination import PageParams, page_params
from ifad_common.security.dependencies import forbid, get_principal, require_permission
from ifad_common.security.policy import AGENT_SCOPES, ROLE_PERMISSIONS
from ifad_common.security.principal import Principal
from ifad_common.security.tokens import mint_agent_token, mint_dev_human_token
from ifad_common.storage import get_storage
from ifad_eval.models import EvaluationRun
from ifad_models import get_gateway
from ifad_rag import Scope, answer_question, ingest_document
from ifad_rag.models import document_summary
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from api_gateway.dev_users import DEV_USERS

router = APIRouter(prefix="/api/v1")
DISCLAIMER = ("Independent demonstration themed on rural development. Not commissioned, endorsed or deployed by IFAD. "
              "All borrower, financial and implementation data is SYNTHETIC.")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------------------- capabilities
@router.get("/platform/capabilities", tags=["platform"], summary="What this platform offers (public)")
async def capabilities():
    s = get_settings()
    return {
        **build_info(), "disclaimer": DISCLAIMER,
        "applications": [
            {"id": "rural-finance", "name": "Rural Finance AI Copilot", "base_path": "/api/v1/finance",
             "capabilities": ["loan intake", "seasonal cash flow", "yield/price/cost/delay scenarios", "risk flags",
                              "cited document Q&A", "human credit review", "decision provenance"]},
            {"id": "project-impact", "name": "Project Monitoring & Impact Copilot", "base_path": "/api/v1/projects",
             "capabilities": ["project registry", "milestones", "budget: commitments vs expenditure, EVM",
                              "indicators", "delay detection", "evidence-backed briefs", "human report approval", "project map"]},
        ],
        "shared_services": ["document ingestion", "RAG with citations and abstention", "model gateway", "pgvector",
                            "object storage", "human review workflows", "hash-chained audit", "evaluation"],
        "model_provider": s.model_provider, "embedding_provider": s.embedding_provider,
        "storage_backend": s.storage_backend, "auth_mode": "dev-tokens (local only)" if s.auth_dev_mode else "oidc",
        "roles": sorted(r for r in ROLE_PERMISSIONS if r != "ai_agent_runtime"),
    }


async def _service_probe(client: httpx.AsyncClient, name: str, base: str) -> dict:
    out = {"service": name, "url": base}
    try:
        health = await client.get(f"{base}/health", headers=outbound_headers())
        ready = await client.get(f"{base}/ready", headers=outbound_headers())
        out.update({"health": health.json(), "ready": ready.json(), "ok": ready.status_code == 200})
    except httpx.HTTPError as exc:
        out.update({"ok": False, "error": type(exc).__name__})
    return out


@router.get("/platform/status", tags=["platform"], summary="Operations view: services, readiness, model, metrics, errors")
async def platform_status(principal: Principal = Depends(require_permission("platform:read"))):
    s = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        services = [await _service_probe(client, "rural-finance", s.finance_service_url),
                    await _service_probe(client, "project-impact", s.projects_service_url)]
    model = await get_gateway().health()
    storage_ok, storage_detail = get_storage().health()
    return {"gateway": {**build_info(), "metrics": metrics.snapshot()}, "services": services, "model": model,
            "storage": {"backend": s.storage_backend, "ok": storage_ok, "detail": storage_detail},
            "deployment": {"target": s.deployment_target, "environment": s.deployment_env}}


@router.get("/platform/services/{service}/metrics", tags=["platform"])
async def service_metrics(service: Literal["rural-finance", "project-impact"],
                          principal: Principal = Depends(require_permission("platform:read"))):
    s = get_settings()
    base = s.finance_service_url if service == "rural-finance" else s.projects_service_url
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        try:
            r = await client.get(f"{base}/internal/metrics", headers=outbound_headers())
            return r.json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"{service} metrics unavailable ({type(exc).__name__})") from exc


# --------------------------------------------------------------------------------------------------------- knowledge
class ScopeRef(Strict):
    domain: Literal["finance", "project"]
    id: str


class KnowledgeQuery(Strict):
    question: str = Field(min_length=3, max_length=500)
    scopes: list[ScopeRef] = Field(min_length=1, max_length=10)
    include_reference: bool = True
    top_k: int = Field(6, ge=1, le=12)


@router.post("/knowledge/query", tags=["knowledge"], summary="Cited answer from documents you may access; abstains without evidence")
def knowledge_query(body: KnowledgeQuery, request: Request, principal: Principal = Depends(require_permission("knowledge:read")),
                    db: Session = Depends(get_db)):
    scopes: list[Scope] = []
    for ref in body.scopes:
        if ref.domain == "finance":
            if "finance:read" not in principal.permissions:
                raise forbid(principal, "Missing permission finance:read", request)
            scopes.append(Scope("finance", ensure_application_access(db, principal, ref.id, request)))
        else:
            if "project:read" not in principal.permissions:
                raise forbid(principal, "Missing permission project:read", request)
            scopes.append(Scope("project", ensure_project_access(db, principal, ref.id, request)))
    if body.include_reference:
        scopes.append(Scope("reference", None))
    answer = answer_question(db, principal, body.question, scopes, top_k=body.top_k)
    append_audit_event(db, principal, "knowledge.queried", subject_type="knowledge", subject_id=None,
                       details={"scopes": [f"{s.domain}:{s.scope_id}" for s in scopes], "abstained": answer.abstained,
                                "citations": [c["chunk_reference"] for c in answer.citations], "grounding": answer.grounding})
    return answer.__dict__


@router.post("/knowledge/ingest", tags=["knowledge"], status_code=201,
             summary="Ingest a tenant-wide reference document (with source and license metadata) or a project document")
async def knowledge_ingest(request: Request, file: UploadFile = File(...),
                           domain: Literal["reference", "project"] = Form(...), project_id: str | None = Form(None),
                           title: str | None = Form(None, max_length=300), source_url: str | None = Form(None, max_length=500),
                           publication_date: date | None = Form(None), license: str | None = Form(None, max_length=200),
                           provenance: Literal["synthetic", "public_reference"] = Form("synthetic"),
                           access_roles: str | None = Form(None, max_length=300),
                           principal: Principal = Depends(require_permission("knowledge:ingest")), db: Session = Depends(get_db)):
    data = await file.read()

    def _store():
        if provenance == "public_reference" and not (source_url and license and publication_date):
            raise DomainError("Public reference documents need source_url, publication_date and license metadata", 422)
        scope_id = None
        if domain == "project":
            if not project_id:
                raise DomainError("project_id is required for project documents", 422)
            scope_id = ensure_project_access(db, principal, project_id, request)
        roles = [r.strip() for r in (access_roles or "").split(",") if r.strip()]
        unknown = [r for r in roles if r not in ROLE_PERMISSIONS]
        if unknown:
            raise DomainError(f"Unknown roles: {', '.join(unknown)}", 422)
        doc, created = ingest_document(db, principal, domain=domain, scope_id=scope_id, filename=file.filename or "upload",
                                       data=data, document_type="public_reference" if provenance == "public_reference" else "reference",
                                       title=title, provenance=provenance, access_roles=roles,
                                       metadata={"source_url": source_url, "license": license,
                                                 "publication_date": publication_date.isoformat() if publication_date else None})
        append_audit_event(db, principal, "document.ingested" if created else "document.duplicate", subject_type="knowledge",
                           subject_id=str(doc.id), details={"domain": domain, "provenance": provenance, "chunks": doc.chunk_count,
                                                            "flags": doc.flags, "source_url": source_url})
        return {**document_summary(doc), "created": created}

    return await run_in_threadpool(_store)


# -------------------------------------------------------------------------------------------------------- evaluation
@router.get("/evaluations/latest", tags=["evaluation"], summary="Latest run of each evaluation suite")
def evaluations_latest(principal: Principal = Depends(require_permission("evaluation:read")), db: Session = Depends(get_db)):
    latest = select(EvaluationRun.suite, func.max(EvaluationRun.created_at).label("at")).group_by(EvaluationRun.suite).subquery()
    rows = db.execute(select(EvaluationRun).join(latest, (EvaluationRun.suite == latest.c.suite) & (EvaluationRun.created_at == latest.c.at))
                      .order_by(EvaluationRun.suite)).scalars()
    return {"items": [{"id": str(r.id), "suite": r.suite, "dataset_version": r.dataset_version, "provider": r.provider,
                       "model": r.model, "embedding_model": r.embedding_model, "prompt_version": r.prompt_version,
                       "code_version": r.code_version, "metrics": r.metrics, "thresholds": r.thresholds, "passed": r.passed,
                       "release_decision": r.release_decision, "failures": r.failures, "created_at": r.created_at.isoformat()}
                      for r in rows]}


# ------------------------------------------------------------------------------------------------------------- audit
@router.get("/audit/events", tags=["audit"], summary="Tenant audit events (auditor)")
def audit_events(page: PageParams = Depends(page_params), event_type: str | None = Query(None, max_length=80),
                 subject_id: str | None = Query(None, max_length=64), actor: str | None = Query(None, max_length=200),
                 principal: Principal = Depends(require_permission("audit:read")), db: Session = Depends(get_db)):
    stmt = select(AuditEvent).where(AuditEvent.tenant_id.in_([principal.tenant_id, "unauthenticated"]))
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if subject_id:
        stmt = stmt.where(AuditEvent.subject_id == subject_id)
    if actor:
        stmt = stmt.where(AuditEvent.actor == actor)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditEvent.id.desc()).limit(page.limit).offset(page.offset)).scalars()
    return {"items": [audit_to_dict(e) for e in rows], "total": total, "limit": page.limit, "offset": page.offset}


@router.get("/audit/verify", tags=["audit"], summary="Verify the tenant's audit hash chain")
def audit_verify(principal: Principal = Depends(require_permission("audit:verify")), db: Session = Depends(get_db)):
    return {"tenant_id": principal.tenant_id, **verify_chain(db, principal.tenant_id)}


# -------------------------------------------------------------------------------------------------------- identities
@router.get("/me", tags=["identity"])
def me(principal: Principal = Depends(get_principal)):
    return {"subject": principal.subject, "kind": principal.kind, "tenant_id": principal.tenant_id,
            "roles": sorted(principal.roles), "permissions": sorted(principal.permissions), "display_name": principal.display_name}


class AgentRunRequest(Strict):
    agent_id: Literal["finance-briefing-agent", "project-briefing-agent"]
    scope_id: str


@router.post("/agents/runs", tags=["identity"], status_code=201,
             summary="Mint a short-lived, scoped agent token for one run (Flowise/orchestrator). Never carries decide rights")
def start_agent_run(body: AgentRunRequest, request: Request, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_db)):
    if not principal.is_human:
        raise forbid(principal, "Only a human can start an agent run", request)
    if body.agent_id == "finance-briefing-agent":
        if "finance:analyze" not in principal.permissions:
            raise forbid(principal, "Missing permission finance:analyze", request)
        scope = ensure_application_access(db, principal, body.scope_id, request)
    else:
        if "project:brief" not in principal.permissions:
            raise forbid(principal, "Missing permission project:brief", request)
        scope = ensure_project_access(db, principal, body.scope_id, request)
    run_id = uuid.uuid4().hex
    token = mint_agent_token(body.agent_id, run_id=run_id, tenant_id=principal.tenant_id, scope_id=str(scope))
    append_audit_event(db, principal, "agent_run.started", subject_type="agent_run", subject_id=run_id,
                       details={"agent_id": body.agent_id, "scope_id": str(scope), "scopes": sorted(AGENT_SCOPES[body.agent_id])})
    return {"run_id": run_id, "agent_id": body.agent_id, "scopes": sorted(AGENT_SCOPES[body.agent_id]),
            "expires_in": get_settings().agent_token_ttl_seconds, "access_token": token}


class DevTokenRequest(Strict):
    username: str = Field(max_length=60)


def _require_dev_mode() -> None:
    if not get_settings().auth_dev_mode:
        raise HTTPException(404, "Not found")


@router.get("/dev/users", tags=["dev-only"], summary="Demo accounts (AUTH_DEV_MODE only)")
def dev_users():
    _require_dev_mode()
    return {"warning": "Development identities. Disabled outside AUTH_DEV_MODE.",
            "users": [{"username": u, **{k: v for k, v in d.items()}} for u, d in DEV_USERS.items()]}


@router.post("/dev/token", tags=["dev-only"], summary="Mint a dev token for a demo account (AUTH_DEV_MODE only)")
def dev_token(body: DevTokenRequest):
    _require_dev_mode()
    user = DEV_USERS.get(body.username)
    if user is None:
        raise HTTPException(404, "Unknown demo user")
    return {"access_token": mint_dev_human_token(body.username, user["roles"], user["tenant"], name=user["name"]),
            "token_type": "bearer", "expires_in": 3600, "username": body.username, **user}
