"""Create .env from .env.example with fresh random local secrets. Never overwrites an existing .env."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANDOM_KEYS = {"POSTGRES_OWNER_PASSWORD", "SVC_GATEWAY_DB_PASSWORD", "SVC_FINANCE_DB_PASSWORD", "SVC_PROJECTS_DB_PASSWORD",
               "AUTH_DEV_JWT_SECRET", "AGENT_TOKEN_SECRET"}


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; leaving it unchanged")
        return 0
    lines = []
    for line in (ROOT / ".env.example").read_text().splitlines():
        key, sep, _ = line.partition("=")
        if sep and key.strip() in RANDOM_KEYS:
            line = f"{key}={secrets.token_urlsafe(36)}"
        lines.append(line)
    target.write_text("\n".join(lines) + "\n")
    target.chmod(0o600)
    print("wrote .env with random local secrets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
