"""Default-deny authorization policy: roles map to explicit permissions; anything unlisted is denied.

Pattern ported from CreditpappraisalFlowise backend/app/auth/policy.py @ d3ff23f with the IFAD platform roles.
"""
from __future__ import annotations

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # Platform operators manage the system, not credit or project decisions.
    "platform_admin": frozenset({"platform:read", "platform:admin", "audit:verify", "evaluation:read"}),
    "finance_analyst": frozenset({
        "finance:read", "finance:create", "finance:analyze", "finance:documents", "finance:submit",
        "knowledge:read", "evaluation:read",
    }),
    "finance_reviewer": frozenset({"finance:read", "finance:review", "finance:decide", "knowledge:read", "evaluation:read"}),
    "project_analyst": frozenset({
        "project:read", "project:create", "project:documents", "project:analyze", "project:brief", "project:submit",
        "knowledge:read", "knowledge:ingest", "evaluation:read",
    }),
    "project_reviewer": frozenset({"project:read", "project:review", "project:decide", "knowledge:read", "evaluation:read"}),
    "auditor": frozenset({"audit:read", "audit:verify", "platform:read", "evaluation:read"}),
    # Agent permissions come only from the agent registry, never from a human role.
    "ai_agent_runtime": frozenset(),
}

# Permissions that only an authenticated human may ever hold, whatever a token claims.
HUMAN_ONLY_PERMISSIONS = frozenset({"finance:decide", "project:decide", "finance:review", "project:review"})

# Scopes for agent runtime identities (Flowise / orchestrator tools). Never includes a HUMAN_ONLY permission.
AGENT_SCOPES: dict[str, frozenset[str]] = {
    "finance-briefing-agent": frozenset({"finance:read", "finance:analyze", "knowledge:read"}),
    "project-briefing-agent": frozenset({"project:read", "project:analyze", "project:brief", "knowledge:read"}),
}
assert not any(scopes & HUMAN_ONLY_PERMISSIONS for scopes in AGENT_SCOPES.values())


def permissions_for_roles(roles: set[str] | frozenset[str]) -> frozenset[str]:
    granted: set[str] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)
