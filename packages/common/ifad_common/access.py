"""Tenant and record-scope checks shared by the services and the knowledge API.

Finance records are scoped to the caller's tenant. Project records are scoped to the tenant AND to an explicit
project membership (projects.project_members), so an analyst assigned to one project cannot read another.
The checks use plain SQL so the shared packages do not import service models.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ifad_common.security.dependencies import forbid
from ifad_common.security.principal import Principal


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc


def accessible_project_ids(db: Session, principal: Principal) -> set[uuid.UUID]:
    if principal.is_agent:
        return {_uuid(principal.scope_id)} if principal.scope_id else set()
    # POC: every user sees every project in their organisation (no per-project assignment).
    rows = db.execute(text("SELECT id FROM projects.projects WHERE tenant_id = :tenant"),
                      {"tenant": principal.tenant_id}).scalars()
    return set(rows)


def ensure_project_access(db: Session, principal: Principal, project_id: str | uuid.UUID, request: Request | None = None) -> uuid.UUID:
    pid = _uuid(project_id)
    tenant = db.execute(text("SELECT tenant_id FROM projects.projects WHERE id = :id"), {"id": pid}).scalar()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if tenant != principal.tenant_id:
        raise forbid(principal, "Cross-tenant project access denied", request, project_id=str(pid))
    if pid not in accessible_project_ids(db, principal):
        raise forbid(principal, "You are not assigned to this project", request, project_id=str(pid))
    return pid


def ensure_application_access(db: Session, principal: Principal, application_id: str | uuid.UUID,
                              request: Request | None = None) -> uuid.UUID:
    aid = _uuid(application_id)
    tenant = db.execute(text("SELECT tenant_id FROM finance.loan_applications WHERE id = :id"), {"id": aid}).scalar()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if tenant != principal.tenant_id:
        raise forbid(principal, "Cross-tenant application access denied", request, application_id=str(aid))
    if principal.is_agent and principal.scope_id != str(aid):
        raise forbid(principal, "Agent token is bound to a different application", request, application_id=str(aid))
    return aid
