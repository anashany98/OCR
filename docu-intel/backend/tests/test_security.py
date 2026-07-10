from typing import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.api.routes.search import csv_safe_cell
from app.database.base import Base
from app.database.init_db import (
    LEGACY_BOOTSTRAP_EMAILS,
    disable_legacy_bootstrap_admin,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_password_hash_roundtrip_and_token_subject():
    password_hash = hash_password("admin123")

    assert password_hash != "admin123"
    assert verify_password("admin123", password_hash)
    assert not verify_password("wrong", password_hash)

    token = create_access_token(subject="42")
    payload = decode_access_token(token)

    assert payload["sub"] == "42"


def test_csv_export_cells_escape_formula_prefixes():
    assert csv_safe_cell("=HYPERLINK(\"http://bad\")") == "'=HYPERLINK(\"http://bad\")"
    assert csv_safe_cell("+SUM(1,2)") == "'+SUM(1,2)"
    assert csv_safe_cell("-10") == "'-10"
    assert csv_safe_cell("@cmd") == "'@cmd"
    assert csv_safe_cell("texto normal") == "texto normal"


# ---------------------------------------------------------------------------
# F0-01 tests: legacy bootstrap admin removal
# ---------------------------------------------------------------------------


def test_no_extra_admins_constant():
    """_EXTRA_ADMINS / hardcoded fixed accounts must not exist."""
    # The module should NOT expose the old constant
    from app.database import init_db
    assert not hasattr(init_db, "_EXTRA_ADMINS")


def test_legacy_email_list_contains_known_address():
    """LEGACY_BOOTSTRAP_EMAILS documents the removed accounts."""
    assert "anas@admin.com" in LEGACY_BOOTSTRAP_EMAILS


def test_disable_legacy_dry_run_no_writes(db_session):
    """dry_run reports proposed actions without writing."""
    from app.models import User

    # Seed a user matching the legacy email
    user = User(
        email="anas@admin.com",
        name="Anas",
        password_hash=hash_password("123123123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    results = disable_legacy_bootstrap_admin(db_session, dry_run=True)
    assert len(results) == 1
    assert results[0]["action"] == "would_deactivate"
    assert results[0]["email"] == "anas@admin.com"

    # Verify user is STILL active (no write)
    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.email == "anas@admin.com"))
    assert refreshed.is_active is True


def test_disable_legacy_confirmed_deactivates_and_audits(db_session):
    """Confirmed call deactivates legacy account and writes audit log."""
    from app.models import User
    from app.models.audit import AuditLog
    from sqlalchemy import select as sa_select

    user = User(
        email="anas@admin.com",
        name="Anas",
        password_hash=hash_password("123123123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    results = disable_legacy_bootstrap_admin(db_session, dry_run=False, actor_id=999)
    assert results[0]["action"] == "deactivated"

    db_session.expire_all()
    refreshed = db_session.scalar(sa_select(User).where(User.email == "anas@admin.com"))
    assert refreshed.is_active is False

    audit = db_session.scalar(
        sa_select(AuditLog).where(AuditLog.action == "disable_legacy_bootstrap_admin")
    )
    assert audit is not None
    assert audit.entity_id == user.id
    assert audit.details_json["email"] == "anas@admin.com"


def test_disable_legacy_already_inactive(db_session):
    """Already-inactive legacy account is reported, not reprocessed."""
    from app.models import User

    user = User(
        email="anas@admin.com",
        name="Anas",
        password_hash=hash_password("old"),
        role="admin",
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    results = disable_legacy_bootstrap_admin(db_session, dry_run=False)
    assert results[0]["action"] == "already_inactive"


def test_disable_legacy_not_found():
    """Non-existent legacy email returns not_found."""
    # Use a fresh in-memory-like session from the fixture
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database.base import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        results = disable_legacy_bootstrap_admin(db, dry_run=False)
        assert results[0]["action"] == "not_found"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# F0-07 tests: metrics token requirement
# ---------------------------------------------------------------------------


def test_metrics_token_validator_requires_in_staging(monkeypatch):
    """Non-local environments must have METRICS_TOKEN set."""
    from pydantic import ValidationError

    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("METRICS_TOKEN", "")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("ADMIN_PASSWORD", "y" * 22)

    with pytest.raises(ValidationError, match="METRICS_TOKEN"):
        from app.core.config import Settings
        Settings(environment="staging", metrics_token="", jwt_secret="x" * 64, admin_password="y" * 22)


def test_metrics_token_validator_allows_empty_in_local():
    """Local environment can have empty METRICS_TOKEN."""
    from app.core.config import Settings
    s = Settings(environment="local", metrics_token="", jwt_secret="x" * 64, admin_password="y" * 22)
    assert s.metrics_token == ""


def test_metrics_endpoint_allows_local_without_token():
    """Local env: no token → 200."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.services.metrics.endpoint import register_metrics_endpoint

    app = FastAPI()
    register_metrics_endpoint(app)
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_endpoint_blocks_staging_without_token():
    """Non-local env without token configured → 401."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.services.metrics.endpoint import register_metrics_endpoint
    from app.core.config import settings

    old_env = settings.environment
    old_token = settings.metrics_token
    try:
        settings.environment = "staging"
        settings.metrics_token = "secret-token-123"
        app = FastAPI()
        register_metrics_endpoint(app)
        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 401
    finally:
        settings.environment = old_env
        settings.metrics_token = old_token


def test_metrics_endpoint_allows_staging_with_correct_token():
    """Non-local env with correct token → 200."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.services.metrics.endpoint import register_metrics_endpoint
    from app.core.config import settings

    old_env = settings.environment
    old_token = settings.metrics_token
    try:
        settings.environment = "staging"
        settings.metrics_token = "secret-token-123"
        app = FastAPI()
        register_metrics_endpoint(app)
        client = TestClient(app)
        resp = client.get("/metrics", headers={"X-Metrics-Token": "secret-token-123"})
        assert resp.status_code == 200
    finally:
        settings.environment = old_env
        settings.metrics_token = old_token


def test_metrics_endpoint_blocks_staging_wrong_token():
    """Non-local env with wrong token → 401."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.services.metrics.endpoint import register_metrics_endpoint
    from app.core.config import settings

    old_env = settings.environment
    old_token = settings.metrics_token
    try:
        settings.environment = "staging"
        settings.metrics_token = "secret-token-123"
        app = FastAPI()
        register_metrics_endpoint(app)
        client = TestClient(app)
        resp = client.get("/metrics", headers={"X-Metrics-Token": "wrong"})
        assert resp.status_code == 401
    finally:
        settings.environment = old_env
        settings.metrics_token = old_token
