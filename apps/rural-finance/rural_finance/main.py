"""Rural Finance Copilot service."""
from __future__ import annotations

import os

os.environ.setdefault("SERVICE_NAME", "rural-finance")

from ifad_audit import install_denied_access_auditing  # noqa: E402
from ifad_common.app_factory import create_app  # noqa: E402

from rural_finance.routes import router  # noqa: E402

install_denied_access_auditing()
app = create_app(
    "rural-finance",
    "Rural Finance AI Copilot API",
    "Agricultural loan intake, seasonal cash-flow analysis, cited evidence and human credit review. "
    "SYNTHETIC DATA ONLY. Independent demonstration; not commissioned or endorsed by IFAD. "
    "The AI never approves or declines a loan.",
    [router],
)
