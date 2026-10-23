"""Ported verbatim from CreditpappraisalFlowise bank-credit-ai-poc/backend/app/audit.py @ d3ff23f."""
from __future__ import annotations

SENSITIVE_KEY_PARTS = ("password", "secret", "token", "api_key", "access_key", "private_key", "client_secret")


def redact_sensitive_config(config: dict) -> dict:
    redacted = {}
    for key, value in (config or {}).items():
        lowered = str(key).lower()
        if any(part in lowered for part in SENSITIVE_KEY_PARTS):
            redacted[key] = "***REDACTED***"
        elif isinstance(value, dict):
            redacted[key] = redact_sensitive_config(value)
        else:
            redacted[key] = value
    return redacted
