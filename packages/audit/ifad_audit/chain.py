"""Hash-chained audit events, written inside the caller's transaction (flush, never commit).

Ported from CreditpappraisalFlowise backend/app/services/audit_chain.py @ d3ff23f. Changes: generic subject
(type, id) instead of customer_id, service name, actor roles, and a separate committed write for denied access.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from ifad_common.config import get_settings
from ifad_common.correlation import current_correlation_id
from ifad_common.db import new_session
from ifad_common.security.dependencies import set_denied_access_hook
from ifad_common.security.principal import Principal
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ifad_audit.models import AuditEvent
from ifad_audit.redaction import redact_sensitive_config

logger = logging.getLogger(__name__)
GENESIS_HASH = "0" * 64


def _canonical(event: AuditEvent) -> str:
    return json.dumps(
        {
            "tenant_id": event.tenant_id, "event_type": event.event_type, "actor": event.actor,
            "actor_kind": event.actor_kind, "actor_roles": event.actor_roles, "service": event.service,
            "subject_type": event.subject_type, "subject_id": event.subject_id, "run_id": event.run_id,
            "correlation_id": event.correlation_id, "details": event.details, "occurred_at": event.occurred_at,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str,
    )


def _digest(prev_hash: str, event: AuditEvent) -> str:
    return hashlib.sha256((prev_hash + _canonical(event)).encode("utf-8")).hexdigest()


def _lock_tenant_chain(db: Session, tenant_id: str) -> None:
    # Serialise appends per tenant so two writers (even in different services) cannot fork the chain.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"audit:{tenant_id}"})


def append_audit_event(
    db: Session,
    principal: Principal | None,
    event_type: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    details: dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> AuditEvent:
    tenant = tenant_id or (principal.tenant_id if principal else "unknown")
    _lock_tenant_chain(db, tenant)
    last = db.execute(
        select(AuditEvent.hash).where(AuditEvent.tenant_id == tenant).order_by(AuditEvent.id.desc()).limit(1)
    ).scalar_one_or_none()
    event = AuditEvent(
        tenant_id=tenant,
        event_type=event_type,
        actor=principal.actor if principal else "anonymous",
        actor_kind=principal.kind if principal else "anonymous",
        actor_roles=sorted(principal.roles) if principal else [],
        service=get_settings().service_name,
        subject_type=subject_type,
        subject_id=str(subject_id) if subject_id is not None else None,
        run_id=principal.run_id if principal else None,
        correlation_id=current_correlation_id() or None,
        # Round-trip through JSON so the hashed form equals what the database returns later.
        details=json.loads(json.dumps(redact_sensitive_config(details or {}), default=str)),
        occurred_at=datetime.now(UTC).isoformat(timespec="microseconds"),
        prev_hash=last or GENESIS_HASH,
    )
    event.hash = _digest(event.prev_hash, event)
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, tenant_id: str) -> dict[str, Any]:
    events = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.id)).scalars().all()
    expected_prev = GENESIS_HASH
    for event in events:
        if event.prev_hash != expected_prev or _digest(event.prev_hash, event) != event.hash:
            return {"valid": False, "events_checked": len(events), "first_invalid_event_id": event.id, "head_hash": None}
        expected_prev = event.hash
    return {"valid": True, "events_checked": len(events), "first_invalid_event_id": None, "head_hash": expected_prev}


def _audit_denied(principal: Principal | None, reason: str, details: dict) -> None:
    # Own transaction: the request's transaction is about to fail and roll back.
    session = new_session()
    try:
        append_audit_event(session, principal, "access.denied", details={"reason": reason, **details},
                           tenant_id=principal.tenant_id if principal else "unauthenticated")
        session.commit()
    finally:
        session.close()


def install_denied_access_auditing() -> None:
    set_denied_access_hook(_audit_denied)
