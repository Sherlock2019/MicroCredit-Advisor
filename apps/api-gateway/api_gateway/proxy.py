"""Local stand-in for Azure API Management routing: /api/v1/finance/* and /api/v1/projects/* are forwarded to the
owning service with the caller's token (each service re-validates it), a correlation id, a timeout and a body limit.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response
from ifad_common.config import get_settings
from ifad_common.correlation import current_correlation_id
from ifad_common.errors import envelope

router = APIRouter(include_in_schema=False)
_FORWARD = {"authorization", "content-type", "accept"}
_RATE_WINDOW, _RATE_LIMIT = 60.0, 600
_hits: dict[str, deque[float]] = defaultdict(deque)
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = httpx.AsyncClient(timeout=httpx.Timeout(s.downstream_timeout_seconds, connect=3.0),
                                    limits=httpx.Limits(max_connections=50))
    return _client


def _rate_limited(client: str) -> bool:
    now, q = time.monotonic(), _hits[client]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    q.append(now)
    return len(q) > _RATE_LIMIT


async def _forward(request: Request, base_url: str, path: str) -> Response:
    s = get_settings()
    if _rate_limited(request.client.host if request.client else "unknown"):
        return envelope(429, "Rate limit exceeded", headers={"Retry-After": "60"})
    declared = int(request.headers.get("content-length") or 0)
    if declared > s.max_upload_bytes + 1_000_000:
        return envelope(413, "Request body too large")
    body = await request.body()
    if len(body) > s.max_upload_bytes + 1_000_000:
        return envelope(413, "Request body too large")
    headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD}
    headers["X-Correlation-ID"] = current_correlation_id()
    headers["X-Forwarded-By"] = "ifad-api-gateway"
    url = f"{base_url.rstrip('/')}{path}"
    try:
        upstream = await _http().request(request.method, url, params=request.query_params, content=body, headers=headers)
    except httpx.TimeoutException:
        return envelope(504, "Upstream service timed out")
    except httpx.TransportError:
        return envelope(502, "Upstream service unavailable")
    passthrough = {k: v for k, v in upstream.headers.items() if k.lower() in {"content-type", "www-authenticate", "retry-after"}}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=passthrough)


@router.api_route("/api/v1/finance/{path:path}", methods=["GET", "POST"])
async def finance(path: str, request: Request) -> Response:
    return await _forward(request, get_settings().finance_service_url, f"/api/v1/finance/{path}")


@router.api_route("/api/v1/projects", methods=["GET", "POST"])
async def projects_root(request: Request) -> Response:
    return await _forward(request, get_settings().projects_service_url, "/api/v1/projects")


@router.api_route("/api/v1/projects/{path:path}", methods=["GET", "POST"])
async def projects(path: str, request: Request) -> Response:
    return await _forward(request, get_settings().projects_service_url, f"/api/v1/projects/{path}")
