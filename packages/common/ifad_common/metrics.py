"""Per-process request metrics (counts, latency percentiles) and a bounded ring of recent errors.

This is operational telemetry, not business data, so an in-memory store is appropriate. On Azure the same events
go to Log Analytics through stdout JSON logs; these counters feed the portal's Operations page and /metrics.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ifad_common.correlation import current_correlation_id

logger = logging.getLogger("ifad.access")
_lock = threading.Lock()
_latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=2000))
_counts: dict[tuple[str, int], int] = defaultdict(int)
_errors: deque[dict] = deque(maxlen=200)
_started = time.time()
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def route_key(method: str, path: str) -> str:
    return f"{method} {_UUID.sub('{id}', path)}"


def record_error(path: str, kind: str, status: int = 500) -> None:
    with _lock:
        _errors.append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "path": _UUID.sub("{id}", path),
                        "kind": kind, "status": status, "correlation_id": current_correlation_id()})


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 2)


def snapshot() -> dict:
    with _lock:
        routes = []
        for key, values in _latencies.items():
            vals = list(values)
            statuses = {str(s): c for (k, s), c in _counts.items() if k == key}
            routes.append({"route": key, "count": sum(statuses.values()), "statuses": statuses,
                           "p50_ms": _percentile(vals, 50), "p95_ms": _percentile(vals, 95), "max_ms": round(max(vals), 2)})
        total = sum(_counts.values())
        errors5xx = sum(c for (_, s), c in _counts.items() if s >= 500)
        return {"uptime_seconds": round(time.time() - _started), "requests_total": total, "errors_5xx": errors5xx,
                "routes": sorted(routes, key=lambda r: -r["count"]), "recent_errors": list(_errors)[-50:]}


def prometheus_text(service: str) -> str:
    snap = snapshot()
    lines = ["# TYPE ifad_requests_total counter"]
    for route in snap["routes"]:
        for status, count in route["statuses"].items():
            lines.append(f'ifad_requests_total{{service="{service}",route="{route["route"]}",status="{status}"}} {count}')
    lines.append("# TYPE ifad_request_latency_p95_ms gauge")
    for route in snap["routes"]:
        lines.append(f'ifad_request_latency_p95_ms{{service="{service}",route="{route["route"]}"}} {route["p95_ms"]}')
    return "\n".join(lines) + "\n"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            key = route_key(request.method, request.url.path)
            with _lock:
                _latencies[key].append(elapsed)
                _counts[(key, status)] += 1
            if status >= 500:
                record_error(request.url.path, "http_error", status)
            logger.info("request", extra={"route": key, "status": status, "duration_ms": round(elapsed, 2)})
