from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.auth import get_clerk_claims
from backend.platform.app import PlatformAudit, PlatformBase, GymTenant, app, platform_db


@pytest.fixture
def platform_client(monkeypatch) -> Iterator[TestClient]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    monkeypatch.setenv("PLATFORM_ADMIN_CLERK_IDS", "clerk-platform-admin")
    app.dependency_overrides[get_clerk_claims] = lambda: {"sub": "clerk-platform-admin"}
    app.dependency_overrides[platform_db] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_platform_admin_registry_and_audit(platform_client):
    created = platform_client.post("/api/platform/gyms", json={"name": "Gym A", "slug": "gym-a"})
    assert created.status_code == 201, created.text
    gym = created.json()
    assert gym["status"] == "pending_provisioning"
    assert platform_client.get("/api/platform/gyms").json() == [gym]
    assert platform_client.get(f"/api/platform/gyms/{gym['id']}").json() == gym
    assert platform_client.post("/api/platform/gyms", json={"name": "Gym A", "slug": "gym-a"}).status_code == 409
    assert platform_client.get("/api/platform/gyms/no-such-id").status_code == 404
    session = app.dependency_overrides[platform_db]()
    audits = session.scalars(select(PlatformAudit)).all()
    assert len(audits) == 1
    assert audits[0].actor_clerk_user_id == "clerk-platform-admin"


def test_fail_closed_for_regular_staff_and_unconfigured_admin(platform_client, monkeypatch):
    app.dependency_overrides[get_clerk_claims] = lambda: {"sub": "clerk-gym-owner"}
    assert platform_client.get("/api/platform/gyms").status_code == 403
    assert platform_client.post("/api/platform/gyms", json={"name": "Gym B", "slug": "gym-b"}).status_code == 403
    monkeypatch.delenv("PLATFORM_ADMIN_CLERK_IDS")
    app.dependency_overrides[get_clerk_claims] = lambda: {"sub": "clerk-platform-admin"}
    assert platform_client.get("/api/platform/gyms").status_code == 403


def test_invalid_slug_rejected(platform_client):
    response = platform_client.post("/api/platform/gyms", json={"name": "Gym B", "slug": "../../gym"})
    assert response.status_code == 422
