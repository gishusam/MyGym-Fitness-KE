from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.auth import get_clerk_claims
from backend.platform.app import PlatformAudit, PlatformBase, GymTenant, app, platform_db, platform_session_factory
from backend.platform.provisioning import db_name_for_slug, provision


@pytest.fixture
def platform_client(monkeypatch) -> Iterator[tuple[TestClient, Session]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    monkeypatch.setenv("PLATFORM_ADMIN_CLERK_IDS", "clerk-platform-admin")
    app.dependency_overrides[get_clerk_claims] = lambda: {"sub": "clerk-platform-admin"}
    app.dependency_overrides[platform_db] = lambda: session
    with TestClient(app) as client:
        yield client, session
    app.dependency_overrides.clear()
    session.close()
    engine.dispose()


def test_db_names_are_deterministic_and_valid():
    assert db_name_for_slug("fit-zone") == "mygym_tenant_fit_zone"
    with pytest.raises(ValueError):
        db_name_for_slug("../../bad")
    with pytest.raises(ValueError):
        db_name_for_slug("a" * 65)


def test_provisioning_request_requires_admin_and_preserves_gym_status(platform_client):
    client, session = platform_client
    gym = client.post("/api/platform/gyms", json={"name": "Fitness A", "slug": "fitness-a"}).json()
    response = client.post(f"/api/platform/gyms/{gym['id']}/provisioning-request")
    assert response.status_code == 200
    assert response.json()["status"] == "pending_provisioning"
    assert session.scalar(select(PlatformAudit).where(PlatformAudit.event == "provisioning_requested")) is not None
    assert client.post("/api/platform/gyms/nope/provisioning-request").status_code == 404
    app.dependency_overrides[get_clerk_claims] = lambda: {"sub": "clerk-gym-owner"}
    assert client.post(f"/api/platform/gyms/{gym['id']}/provisioning-request").status_code == 403


def test_dry_run_does_not_change_tenant(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}")
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as session:
        gym = GymTenant(id=str(uuid4()), name="Gym A", slug="gym-a")
        session.add(gym)
        session.commit()
        gym_id = gym.id
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr("backend.platform.provisioning.platform_session_factory", lambda: sessionmaker(bind=engine))
    assert provision(gym_id) == "mygym_tenant_gym_a"
    with Session(engine) as session:
        assert session.get(GymTenant, gym_id).status == "pending_provisioning"
        assert session.scalars(select(PlatformAudit)).all() == []
    engine.dispose()
