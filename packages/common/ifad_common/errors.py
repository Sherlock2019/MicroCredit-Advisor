"""Standard error envelope: {"error": {code, message, correlation_id, details}}.

Ported from CreditpappraisalFlowise bank-credit-ai-poc/backend/app/errors.py @ d3ff23f, applied to every route.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ifad_common.correlation import current_correlation_id
from ifad_common.metrics import record_error

logger = logging.getLogger(__name__)

_CODES = {
    400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict",
    413: "payload_too_large", 415: "unsupported_media_type", 422: "validation_error", 429: "rate_limited",
    502: "bad_gateway", 503: "unavailable", 504: "gateway_timeout",
}


class DomainError(Exception):
    """A business-rule violation that is safe to show to the caller."""

    def __init__(self, message: str, status_code: int = 409, details: object | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


def envelope(status: int, message: str, details=None, headers=None) -> JSONResponse:
    body = {"error": {"code": _CODES.get(status, "error"), "message": message,
                      "correlation_id": current_correlation_id(), "details": details}}
    return JSONResponse(status_code=status, content=jsonable_encoder(body), headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        return envelope(exc.status_code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # Drop the echoed input: it can contain uploaded content or personal data.
        details = [{k: v for k, v in err.items() if k in {"loc", "msg", "type"}} for err in exc.errors()]
        return envelope(422, "Request validation failed", details=details)

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError):
        return envelope(exc.status_code, str(exc), details=exc.details)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        logger.exception("Unhandled error correlation_id=%s", current_correlation_id())
        record_error(request.url.path, type(exc).__name__)
        # No exception text in the response: it can contain SQL, prompts or borrower data.
        return envelope(500, "Internal error")
