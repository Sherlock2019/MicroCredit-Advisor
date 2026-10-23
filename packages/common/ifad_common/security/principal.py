"""Authenticated caller. Ported from CreditpappraisalFlowise backend/app/auth/principal.py @ d3ff23f."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Principal:
    """Built only from a validated token, never from request bodies or prompts."""

    subject: str
    kind: Literal["human", "agent"]
    tenant_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    display_name: str | None = None
    # Agent runtime identities only: which agent, which run and which business record the token is bound to.
    agent_id: str | None = None
    run_id: str | None = None
    scope_id: str | None = None

    @property
    def is_human(self) -> bool:
        return self.kind == "human"

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"

    @property
    def actor(self) -> str:
        return f"agent:{self.agent_id}" if self.is_agent else self.subject
