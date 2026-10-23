"""Workflow state machines with server-side actor rules.

Per-domain reviewer authority follows SupplyChain_Predictions backend/scinsight/security.py::REVIEW_AUTHORITY
@ 5c8dce6; four-eyes/segregation of duties follows the Banking copilot's approval gate. Final states can only be
reached by an authenticated human holding the domain's decide permission. Agents and the system can never reach them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ifad_audit import append_audit_event
from ifad_common.errors import DomainError
from ifad_common.security.principal import Principal
from sqlalchemy.orm import Session

from ifad_review.models import ReviewDecision


class TransitionError(DomainError):
    pass


@dataclass(frozen=True)
class Transition:
    to_state: str
    permission: str          # permission the actor must hold
    human_only: bool = True
    reason_required: bool = False
    evidence_required: bool = False
    not_by_creator: bool = False  # segregation of duties: the preparer cannot decide


@dataclass(frozen=True)
class Workflow:
    name: str
    subject_type: str
    transitions: dict[str, tuple[Transition, ...]]
    final_states: frozenset[str] = field(default_factory=frozenset)

    def allowed(self, from_state: str) -> list[str]:
        return [t.to_state for t in self.transitions.get(from_state, ())]

    def find(self, from_state: str, to_state: str) -> Transition:
        for t in self.transitions.get(from_state, ()):
            if t.to_state == to_state:
                return t
        allowed = ", ".join(self.allowed(from_state)) or "none (final state)"
        raise TransitionError(f"{self.subject_type} cannot move from {from_state} to {to_state}; allowed: {allowed}")


# A5: DRAFT -> SUBMITTED -> ANALYZED -> IN_REVIEW -> NEEDS_INFORMATION -> APPROVED / DECLINED
FINANCE_WORKFLOW = Workflow(
    name="rural-finance-credit-review",
    subject_type="loan_application",
    transitions={
        "DRAFT": (Transition("SUBMITTED", "finance:submit"),),
        "SUBMITTED": (Transition("ANALYZED", "finance:analyze", human_only=False),),
        "ANALYZED": (Transition("ANALYZED", "finance:analyze", human_only=False),
                     Transition("IN_REVIEW", "finance:submit")),
        "IN_REVIEW": (
            Transition("NEEDS_INFORMATION", "finance:review", reason_required=True),
            Transition("APPROVED", "finance:decide", reason_required=True, evidence_required=True, not_by_creator=True),
            Transition("DECLINED", "finance:decide", reason_required=True, evidence_required=True, not_by_creator=True),
        ),
        "NEEDS_INFORMATION": (Transition("SUBMITTED", "finance:submit"),),
    },
    final_states=frozenset({"APPROVED", "DECLINED"}),
)

PROJECT_REPORT_WORKFLOW = Workflow(
    name="project-brief-approval",
    subject_type="project_brief",
    transitions={
        "DRAFT": (Transition("SUBMITTED", "project:submit"),),
        "SUBMITTED": (
            Transition("CHANGES_REQUESTED", "project:review", reason_required=True),
            Transition("APPROVED", "project:decide", reason_required=True, evidence_required=True, not_by_creator=True),
        ),
        "CHANGES_REQUESTED": (Transition("SUBMITTED", "project:submit"),),
    },
    final_states=frozenset({"APPROVED"}),
)


def record_transition(db: Session, principal: Principal, workflow: Workflow, *, subject_id: uuid.UUID, created_by: str,
                      from_state: str, to_state: str, reason: str | None = None, evidence_refs: list[str] | None = None,
                      versions: dict | None = None) -> ReviewDecision:
    # Authority first, state second: an unauthorised caller learns nothing about the record's state.
    candidates = [t for ts in workflow.transitions.values() for t in ts if t.to_state == to_state]
    if (to_state in workflow.final_states or any(t.human_only for t in candidates)) and not principal.is_human:
        raise TransitionError(f"{to_state} can only be recorded by an authenticated human", 403)
    if candidates and not any(t.permission in principal.permissions for t in candidates):
        raise TransitionError(f"Missing permission {candidates[0].permission} for {to_state}", 403)
    transition = workflow.find(from_state, to_state)
    if transition.permission not in principal.permissions:
        raise TransitionError(f"Missing permission {transition.permission} for {to_state}", 403)
    if transition.reason_required and not (reason and reason.strip()):
        raise TransitionError(f"A reason is required to move to {to_state}", 422)
    if transition.evidence_required and not evidence_refs:
        raise TransitionError(f"List the evidence reviewed before recording {to_state}", 422)
    if transition.not_by_creator and principal.subject == created_by:
        raise TransitionError("Segregation of duties: the person who prepared this record cannot decide it", 403)

    event = append_audit_event(db, principal, f"{workflow.subject_type}.state_changed", subject_type=workflow.subject_type,
                               subject_id=str(subject_id),
                               details={"from_state": from_state, "to_state": to_state, "reason": reason,
                                        "evidence_refs": evidence_refs or [], "versions": versions or {},
                                        "final": to_state in workflow.final_states})
    decision = ReviewDecision(tenant_id=principal.tenant_id, workflow=workflow.name, subject_type=workflow.subject_type,
                              subject_id=subject_id, from_state=from_state, to_state=to_state, actor=principal.actor,
                              actor_kind=principal.kind, actor_roles=sorted(principal.roles), reason=reason,
                              evidence_refs=evidence_refs or [], versions=versions or {}, audit_event_id=event.id)
    db.add(decision)
    db.flush()
    return decision
