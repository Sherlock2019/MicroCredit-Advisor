"""Demo identities for local development ONLY (AUTH_DEV_MODE=true). In Azure these are Entra ID users with app roles."""
from __future__ import annotations

TENANT_A = "tenant-demo-a"  # "Synthetic Partner Organisation A"
TENANT_B = "tenant-demo-b"  # "Synthetic Partner Organisation B"

DEV_USERS: dict[str, dict] = {
    "fatima.finance": {"name": "Fatima (finance analyst)", "roles": ["finance_analyst"], "tenant": TENANT_A},
    "kofi.credit": {"name": "Kofi (finance reviewer)", "roles": ["finance_reviewer"], "tenant": TENANT_A},
    "ana.project": {"name": "Ana (project analyst)", "roles": ["project_analyst"], "tenant": TENANT_A},
    "omar.project": {"name": "Omar (project analyst, one project only)", "roles": ["project_analyst"], "tenant": TENANT_A},
    "rita.reviewer": {"name": "Rita (project reviewer)", "roles": ["project_reviewer"], "tenant": TENANT_A},
    "aude.auditor": {"name": "Aude (auditor)", "roles": ["auditor"], "tenant": TENANT_A},
    "admin.platform": {"name": "Platform admin", "roles": ["platform_admin"], "tenant": TENANT_A},
    "bea.tenantb": {"name": "Bea (analyst, partner organisation B)", "roles": ["finance_analyst", "project_analyst"], "tenant": TENANT_B},
}
