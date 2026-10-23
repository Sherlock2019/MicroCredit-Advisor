"""FastAPI guards. Every /api/v1 business route declares one; denied attempts are written to the audit chain.

Ported from CreditpappraisalFlowise backend/app/auth/dependencies.py @ d3ff23f; adds denied-access auditing.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status

from ifad_common.security.policy import HUMAN_ONLY_PERMISSIONS
from ifad_common.security.principal import Principal
from ifad_common.security.tokens import AuthError, principal_from_token

logger = logging.getLogger(__name__)

# Set by services that have the audit package wired in: fn(principal | None, action, details) -> None
_denied_hook: Callable[[Principal | None, str, dict], None] | None = None


def set_denied_access_hook(hook: Callable[[Principal | None, str, dict], None]) -> None:
    global _denied_hook
    _denied_hook = hook


def record_denied(principal: Principal | None, reason: str, request: Request | None = None, **details) -> None:
    if request is not None:
        details.setdefault("method", request.method)
        details.setdefault("path", request.url.path)
    if _denied_hook is None:
        logger.warning("access denied", extra={"reason": reason, **details})
        return
    try:
        _denied_hook(principal, reason, details)
    except Exception:  # noqa: BLE001 - denial must still be returned even if auditing fails
        logger.exception("could not audit denied access")


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message, headers={"WWW-Authenticate": "Bearer"})


def get_principal(request: Request) -> Principal:
    token = _bearer(request)
    if token is None:
        record_denied(None, "missing_token", request)
        raise _unauthorized("Bearer token required")
    try:
        principal = principal_from_token(token)
    except AuthError as exc:
        record_denied(None, "invalid_token", request, error=str(exc)[:200])
        raise _unauthorized(str(exc)) from exc
    request.state.principal = principal
    return principal


def forbid(principal: Principal, message: str, request: Request | None = None, **details) -> HTTPException:
    record_denied(principal, message, request, **details)
    return HTTPException(status_code=403, detail=message)


def require_permission(permission: str) -> Callable[..., Principal]:
    """Route guard. Agents are rejected for human-only permissions whatever their token says."""

    def guard(request: Request, principal: Principal = Depends(get_principal)) -> Principal:
        if permission in HUMAN_ONLY_PERMISSIONS and not principal.is_human:
            raise forbid(principal, f"{permission} requires an authenticated human", request, permission=permission)
        if permission not in principal.permissions:
            raise forbid(principal, f"Missing permission {permission}", request, permission=permission)
        return principal

    return guard
