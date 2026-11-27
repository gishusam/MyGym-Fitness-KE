"""Focused tenant-routing authorization tests (no real Clerk or DB credentials)."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import importlib

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.core.auth import get_clerk_claims, get_current_staff
from backend.app.db.session import get_db
from backend.app.db import tenant_sessions


@pytest.fixture
def setup(monkeypatch):
    current = {"sub": "user_demo"}
    gyms = {
        "mygym": SimpleNamespace(status="active", database_ref="mygym_fitness_dev", environment_kind="development"),
        "demo": SimpleNamespace(status="active", database_ref="mygym_demo", environment_kind="demo"),
        "sams": SimpleNamespace(status="active", database_ref="mygym_tenant_sam_s_4298894e", environment_kind="customer"),
    }
    memberships = {
        "mygym_fitness_dev": {"user_mygym"},
        "mygym_demo": {"user_demo", "user_admin"},
        "mygym_tenant_sam_s_4298894e": {"user_sam"},
    }
    accessed, writes = [], []

    class Registry:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, model, gym_id): return gyms.get(gym_id)

    class GymSession:
        def __init__(self, name): self.name = name; self.info = {}
        def scalar(self, query):
            # Evaluate the subject genuinely used by the SQLAlchemy WHERE clause.
            params = query.compile().params
            subject = next((v for k, v in params.items() if "clerk_user_id" in k), None)
            if subject not in memberships[self.name]:
                return None
            from backend.app.models.staff_user import StaffStatus, StaffRole
            return SimpleNamespace(id=uuid4(), clerk_user_id=subject, name="Test Staff",
                                   email="test@example.test", role=StaffRole.OWNER.value,
                                   status=StaffStatus.ACTIVE.value)
        def close(self): pass
        def rollback(self): pass

    def factory(name):
        def make_session():
            accessed.append(name)
            return GymSession(name)
        return make_session

    platform = importlib.import_module("backend.platform.app")
    auth = importlib.import_module("backend.app.core.auth")
    config = importlib.import_module("backend.app.config")
    monkeypatch.setattr(platform, "platform_session_factory", lambda: lambda: Registry())
    monkeypatch.setattr(tenant_sessions, "existing_factory", factory)
    monkeypatch.setattr(tenant_sessions, "tenant_factory", factory)
    monkeypatch.setattr(auth, "get_clerk_claims", lambda request, settings: {"sub": current["sub"]})
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setenv("PLATFORM_ADMIN_CLERK_IDS", "user_admin")

    app = FastAPI()
    app.dependency_overrides[get_clerk_claims] = lambda: {"sub": current["sub"]}

    @app.get("/api/members")
    def read_members(staff=Depends(get_current_staff), db=Depends(get_db)):
        return {"database": db.name}

    @app.post("/api/payments")
    def write_payment(request: Request, staff=Depends(get_current_staff), db=Depends(get_db)):
        writes.append(db.name)
        return {"database": db.name}

    with TestClient(app) as client:
        yield client, current, accessed, writes
    app.dependency_overrides.clear()


def test_demofit_routed_to_demofit_database(setup):
    client, subject, accessed, _ = setup
    assert client.get("/api/members", cookies={"mygym_gym": "demo"}).json() == {"database": "mygym_demo"}
    assert accessed == ["mygym_demo"]


def test_mygym_member_routed_to_mygym_database(setup):
    client, subject, accessed, _ = setup
    subject["sub"] = "user_mygym"
    assert client.get("/api/members", cookies={"mygym_gym": "mygym"}).json() == {"database": "mygym_fitness_dev"}
    assert accessed == ["mygym_fitness_dev"]


def test_missing_cookie_never_uses_default_database(setup, monkeypatch):
    client, _, accessed, _ = setup
    session_module = importlib.import_module("backend.app.db.session")
    monkeypatch.setattr(session_module, "get_session_factory", lambda: pytest.fail("unsafe default database fallback"))
    response = client.get("/api/members")
    assert response.status_code == 403
    assert accessed == []


def test_demofit_user_cannot_read_mygym(setup):
    client, _, _, _ = setup
    assert client.get("/api/members", cookies={"mygym_gym": "mygym"}).status_code == 403


def test_demofit_user_cannot_read_sams_or_write_to_it(setup):
    client, _, _, writes = setup
    assert client.get("/api/members", cookies={"mygym_gym": "sams"}).status_code == 403
    assert client.post("/api/payments", cookies={"mygym_gym": "sams"}).status_code == 403
    assert writes == []


def test_url_header_and_body_do_not_override_verified_gym(setup):
    client, _, accessed, writes = setup
    response = client.post("/api/payments?gym_id=mygym", cookies={"mygym_gym": "demo"},
                           headers={"X-Gym-ID": "mygym"}, json={"gym_id": "mygym"})
    assert response.status_code == 200
    assert response.json()["database"] == "mygym_demo"
    assert writes == ["mygym_demo"]
    assert accessed == ["mygym_demo"]


def test_super_admin_cannot_use_gym_data_api_even_with_staff_membership(setup):
    client, subject, accessed, writes = setup
    subject["sub"] = "user_admin"
    assert client.get("/api/members", cookies={"mygym_gym": "demo"}).status_code == 403
    assert client.post("/api/payments", cookies={"mygym_gym": "demo"}).status_code == 403
    assert accessed == []
    assert writes == []
