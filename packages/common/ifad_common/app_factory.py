"""Builds a FastAPI service with the platform middleware, error envelope, health and readiness probes."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, FastAPI
from fastapi import encoders as fastapi_encoders
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from ifad_common import metrics
from ifad_common.config import get_settings
from ifad_common.correlation import CorrelationIdMiddleware
from ifad_common.db import database_ready
from ifad_common.errors import register_error_handlers
from ifad_common.logging_setup import configure_logging

ReadinessCheck = Callable[[], tuple[bool, str]]

# Money and ratios are Decimal end to end; serialise them as strings so JSON clients never see float rounding.
fastapi_encoders.ENCODERS_BY_TYPE[Decimal] = str


def build_info() -> dict:
    s = get_settings()
    return {"service": s.service_name, "version": s.build_version, "commit_sha": s.commit_sha,
            "environment": s.deployment_env, "deployment_target": s.deployment_target}


def create_app(service: str, title: str, description: str, routers: Sequence[APIRouter],
               extra_checks: dict[str, ReadinessCheck] | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(service)
    app = FastAPI(title=title, description=description, version=settings.build_version,
                  openapi_url="/openapi.json", docs_url="/docs", redoc_url=None)
    app.add_middleware(metrics.MetricsMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
                       expose_headers=["X-Correlation-ID"])
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)
    checks: dict[str, ReadinessCheck] = {"database": database_ready, **(extra_checks or {})}

    @app.get("/health", tags=["operations"], summary="Liveness: the process is serving requests")
    def health() -> dict:
        return {"status": "ok", "at": datetime.now(UTC).isoformat(timespec="seconds"), **build_info()}

    @app.get("/ready", tags=["operations"], summary="Readiness: dependencies are reachable")
    def ready():
        results = {}
        for name, check in checks.items():
            ok, detail = check()
            results[name] = {"ok": ok, "detail": detail}
        all_ok = all(r["ok"] for r in results.values())
        return JSONResponse(status_code=200 if all_ok else 503,
                            content={"status": "ready" if all_ok else "not_ready", "checks": results, **build_info()})

    @app.get("/metrics", tags=["operations"], include_in_schema=False)
    def prometheus() -> PlainTextResponse:
        return PlainTextResponse(metrics.prometheus_text(service))

    # Internal network only: not routed by the gateway proxy or APIM; NetworkPolicy restricts it on AKS.
    @app.get("/internal/metrics", tags=["operations"], include_in_schema=False)
    def internal_metrics() -> dict:
        return {"service": service, **metrics.snapshot()}

    for router in routers:
        app.include_router(router)
    return app
