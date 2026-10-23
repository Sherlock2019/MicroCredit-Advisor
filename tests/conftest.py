"""Test configuration.

Unit tests need nothing. Integration, security, e2e and evaluation tests need PostgreSQL/pgvector: they create a
separate database `ifad_platform_test` next to DATABASE_URL (owner role), migrate it with Alembic, seed the SYNTHETIC
demo data through the real service code, and route the gateway's proxy in-process to the two business services.
"""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_BASE_URL = os.environ.get("DATABASE_URL", "")
DB_AVAILABLE = _BASE_URL.startswith("postgresql")
TEST_DB = "ifad_platform_test"
if DB_AVAILABLE:
    os.environ["DATABASE_URL"] = _BASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
os.environ.update({
    "SERVICE_NAME": "test-suite", "DEPLOYMENT_ENV": "test", "AUTH_DEV_MODE": "true", "MODEL_PROVIDER": "mock",
    "EMBEDDING_PROVIDER": "hash", "EMBEDDING_DIM": "384", "FINANCE_SERVICE_URL": "http://finance.test",
    "PROJECTS_SERVICE_URL": "http://projects.test", "STORAGE_LOCAL_ROOT": str(ROOT / "data" / "test-object-store"),
})
os.environ.setdefault("AUTH_DEV_JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("AGENT_TOKEN_SECRET", secrets.token_urlsafe(48))


def pytest_collection_modifyitems(config, items):
    if DB_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="DATABASE_URL not set: run `make db-up migrate` and `make test`")
    for item in items:
        if "/unit/" not in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database():
    if not DB_AVAILABLE:
        pytest.skip("no database")
    import shutil

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    admin = create_engine(_BASE_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    admin.dispose()
    shutil.rmtree(os.environ["STORAGE_LOCAL_ROOT"], ignore_errors=True)
    command.upgrade(Config(str(ROOT / "database" / "alembic.ini")), "head")

    from ifad_common.db import new_session

    from scripts.seed_demo import seed_finance, seed_projects

    session = new_session()
    seed_finance(session)
    seed_projects(session)
    session.commit()
    session.close()
    yield os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def apps(database):
    import api_gateway.proxy as proxy
    import httpx
    from api_gateway.main import app as gateway_app
    from project_impact.main import app as projects_app
    from rural_finance.main import app as finance_app

    proxy._client = httpx.AsyncClient(mounts={"http://finance.test": httpx.ASGITransport(app=finance_app),
                                              "http://projects.test": httpx.ASGITransport(app=projects_app)},
                                      timeout=httpx.Timeout(30.0))
    return {"gateway": gateway_app, "finance": finance_app, "projects": projects_app}


@pytest.fixture(scope="session")
def gateway(apps):
    from fastapi.testclient import TestClient

    with TestClient(apps["gateway"]) as client:
        yield client


@pytest.fixture(scope="session")
def finance(apps):
    from fastapi.testclient import TestClient

    with TestClient(apps["finance"]) as client:
        yield client


@pytest.fixture(scope="session")
def projects(apps):
    from fastapi.testclient import TestClient

    with TestClient(apps["projects"]) as client:
        yield client


def token_for(username: str, **overrides) -> str:
    from api_gateway.dev_users import DEV_USERS
    from ifad_common.security.tokens import mint_dev_human_token

    user = {**DEV_USERS[username], **overrides}
    return mint_dev_human_token(username, user["roles"], user["tenant"], name=user["name"])


def auth(username: str, **overrides) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(username, **overrides)}"}


@pytest.fixture
def as_user():
    return auth


@pytest.fixture
def db_session(database):
    from ifad_common.db import new_session

    session = new_session()
    yield session
    session.rollback()
    session.close()


def find_application(session, pseudonym: str):
    from rural_finance.models import LoanApplication
    from sqlalchemy import select

    return session.execute(select(LoanApplication).where(LoanApplication.borrower_pseudonym == pseudonym)).scalar_one()


def find_project(session, code: str):
    from project_impact.models import Project
    from sqlalchemy import select

    return session.execute(select(Project).where(Project.code == code)).scalar_one()


@pytest.fixture
def unique():
    return lambda prefix="T": f"{prefix}{int(time.time() * 1000) % 10_000_000:07d}{secrets.randbelow(100)}"
