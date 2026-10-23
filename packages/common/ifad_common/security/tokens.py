"""Token validation for humans (Entra ID / OIDC, or dev HS256) and run-bound agent tokens.

Ported from CreditpappraisalFlowise backend/app/auth/tokens.py @ d3ff23f. Changes: Entra ID v2 `roles` claim,
IFAD roles, agent scopes from ifad_common.security.policy, scope_id instead of an integer customer id.
"""
from __future__ import annotations

import logging
import secrets
import time
from functools import lru_cache
from typing import Any

import jwt

from ifad_common.config import get_settings
from ifad_common.security.policy import AGENT_SCOPES, permissions_for_roles
from ifad_common.security.principal import Principal

logger = logging.getLogger(__name__)

AGENT_ISSUER = "ifad-platform-agent-runtime"
AGENT_AUDIENCE = "ifad-platform-tools"
_LEEWAY_SECONDS = 30


class AuthError(Exception):
    """Raised for any token problem. The message is safe to return to the caller."""


@lru_cache
def _agent_signing_secret() -> str:
    secret = get_settings().agent_token_secret
    if secret:
        return secret
    logger.warning("AGENT_TOKEN_SECRET is not set; using a per-process random secret (single worker only).")
    return secrets.token_urlsafe(48)


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


# ---------------------------------------------------------------------------------------------------------- agents
def mint_agent_token(agent_id: str, *, run_id: str, tenant_id: str, scope_id: str, ttl_seconds: int | None = None) -> str:
    if agent_id not in AGENT_SCOPES:
        raise ValueError(f"Unknown agent identity: {agent_id}")
    now = int(time.time())
    claims = {
        "iss": AGENT_ISSUER, "aud": AGENT_AUDIENCE, "sub": f"agent:{agent_id}", "agent_id": agent_id,
        "run_id": run_id, "tenant_id": tenant_id, "scope_id": scope_id,
        "iat": now, "exp": now + (ttl_seconds or get_settings().agent_token_ttl_seconds), "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, _agent_signing_secret(), algorithm="HS256")


def _validate_agent_token(token: str) -> Principal:
    try:
        claims = jwt.decode(token, _agent_signing_secret(), algorithms=["HS256"], audience=AGENT_AUDIENCE,
                            issuer=AGENT_ISSUER, leeway=_LEEWAY_SECONDS,
                            options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid agent token: {exc}") from exc
    agent_id = claims.get("agent_id") or ""
    if agent_id not in AGENT_SCOPES or claims.get("sub") != f"agent:{agent_id}":
        raise AuthError("Unknown agent identity")
    # Scopes come from the registry, not the token, so a revoked scope takes effect immediately.
    return Principal(subject=claims["sub"], kind="agent", tenant_id=str(claims["tenant_id"]),
                     roles=frozenset({"ai_agent_runtime"}), permissions=AGENT_SCOPES[agent_id],
                     agent_id=agent_id, run_id=str(claims["run_id"]), scope_id=str(claims["scope_id"]))


# ---------------------------------------------------------------------------------------------------------- humans
def _roles_from_claims(claims: dict[str, Any]) -> set[str]:
    roles = set(claims.get("roles") or [])  # Entra ID app roles
    roles |= set((claims.get("realm_access") or {}).get("roles") or [])  # Keycloak (kept from the source)
    return {str(role).replace("-", "_").replace(".", "_").lower() for role in roles}


def _human_principal(claims: dict[str, Any]) -> Principal:
    settings = get_settings()
    tenant_id = claims.get(settings.oidc_tenant_claim)
    if not tenant_id:
        raise AuthError(f"Token has no {settings.oidc_tenant_claim} claim")
    roles = _roles_from_claims(claims)
    # A human token can never carry agent identity, even if someone adds the role in the IdP.
    roles.discard("ai_agent_runtime")
    subject = str(claims.get("preferred_username") or claims.get("upn") or claims["sub"])
    return Principal(subject=subject, kind="human", tenant_id=str(tenant_id), roles=frozenset(roles),
                     permissions=permissions_for_roles(roles), display_name=claims.get("name"))


def _validate_human_token(token: str) -> Principal:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError(f"Malformed token: {exc}") from exc
    options = {"require": ["exp", "iat", "sub", "aud", "iss"]}
    if header.get("alg") == "HS256":
        if not (settings.auth_dev_mode and settings.auth_dev_jwt_secret):
            raise AuthError("HS256 tokens are only accepted in AUTH_DEV_MODE")
        key, algorithms, issuer = settings.auth_dev_jwt_secret, ["HS256"], settings.auth_dev_issuer
    else:
        if not (settings.oidc_jwks_url and settings.oidc_issuer):
            raise AuthError("OIDC is not configured (OIDC_ISSUER / OIDC_JWKS_URL)")
        try:
            key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token).key
        except jwt.PyJWTError as exc:
            raise AuthError(f"Signing key not found: {exc}") from exc
        algorithms, issuer = ["RS256"], settings.oidc_issuer
    try:
        claims = jwt.decode(token, key, algorithms=algorithms, audience=settings.oidc_audience, issuer=issuer,
                            leeway=_LEEWAY_SECONDS, options=options)
    except jwt.PyJWTError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc
    return _human_principal(claims)


def principal_from_token(token: str) -> Principal:
    try:
        issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.PyJWTError as exc:
        raise AuthError(f"Malformed token: {exc}") from exc
    # The issuer only picks which verification applies; every path verifies the signature.
    if issuer == AGENT_ISSUER:
        return _validate_agent_token(token)
    return _validate_human_token(token)


def mint_dev_human_token(username: str, roles: list[str], tenant_id: str, *, name: str | None = None,
                         ttl_seconds: int = 3600) -> str:
    settings = get_settings()
    if not (settings.auth_dev_mode and settings.auth_dev_jwt_secret):
        raise RuntimeError("Set AUTH_DEV_MODE=true and AUTH_DEV_JWT_SECRET to mint dev tokens")
    now = int(time.time())
    claims = {
        "iss": settings.auth_dev_issuer, "aud": settings.oidc_audience, "sub": f"dev|{username}",
        "preferred_username": username, "name": name or username, "roles": roles,
        settings.oidc_tenant_claim: tenant_id, "iat": now, "exp": now + ttl_seconds,
    }
    return jwt.encode(claims, settings.auth_dev_jwt_secret, algorithm="HS256")
