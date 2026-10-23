"""Project Monitoring & Impact Copilot service."""
from __future__ import annotations

import os

os.environ.setdefault("SERVICE_NAME", "project-impact")

from ifad_audit import install_denied_access_auditing  # noqa: E402
from ifad_common.app_factory import create_app  # noqa: E402

from project_impact.routes import router  # noqa: E402

install_denied_access_auditing()
app = create_app(
    "project-impact",
    "Project Monitoring & Impact Copilot API",
    "Project registry, milestones, budget (commitments vs expenditure), indicators, field-report evidence, "
    "rule-based delay detection, evidence-backed briefs and human report approval. SYNTHETIC DATA ONLY. "
    "Independent demonstration; not commissioned or endorsed by IFAD.",
    [router],
)
