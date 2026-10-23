"""API gateway: platform routes + local routing to the business services (Azure API Management in the cloud)."""
from __future__ import annotations

import os

os.environ.setdefault("SERVICE_NAME", "api-gateway")

from ifad_audit import install_denied_access_auditing  # noqa: E402
from ifad_common.app_factory import create_app  # noqa: E402
from ifad_common.storage import get_storage  # noqa: E402

from api_gateway.platform_routes import router as platform_router  # noqa: E402
from api_gateway.proxy import router as proxy_router  # noqa: E402

install_denied_access_auditing()
app = create_app(
    "api-gateway",
    "IFAD-themed Rural AI Platform — Gateway",
    "Shared platform API (capabilities, knowledge/RAG, evaluations, audit, identities) and routing to the Rural Finance "
    "and Project Impact services. Independent demonstration; not commissioned or endorsed by IFAD. SYNTHETIC DATA.",
    [platform_router, proxy_router],
    extra_checks={"object_storage": lambda: get_storage().health()},
)
