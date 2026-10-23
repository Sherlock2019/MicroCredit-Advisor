"""Correlation ids: accepted from X-Correlation-ID / X-Request-ID or generated, echoed on every response.

Ported from CreditpappraisalFlowise bank-credit-ai-poc/backend/app/correlation.py @ d3ff23f.
"""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def current_correlation_id() -> str:
    return correlation_id_var.get()


def outbound_headers() -> dict[str, str]:
    """Headers that carry the correlation id to downstream services."""
    cid = current_correlation_id()
    return {"X-Correlation-ID": cid} if cid else {}


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or ""
        correlation_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
