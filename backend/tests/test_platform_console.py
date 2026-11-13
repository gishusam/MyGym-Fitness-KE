"""Platform UI API support: audit visibility and tenant scoping."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.auth import get_clerk_claims
from backend.platform.app import app, PlatformBase, platform_db


def test_gym_audit_is_admin_only_and_scoped(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    monkeypatch.setenv('PLATFORM_ADMIN_CLERK_IDS', 'platform-user')
    with Session(engine, expire_on_commit=False) as session:
        app.dependency_overrides[get_clerk_claims] = lambda: {'sub': 'platform-user'}
        app.dependency_overrides[platform_db] = lambda: session
        try:
            with TestClient(app) as client:
                first = client.post('/api/platform/gyms', json={'name':'Gym One','slug':'gym-one'}).json()
                second = client.post('/api/platform/gyms', json={'name':'Gym Two','slug':'gym-two'}).json()
                response = client.get(f"/api/platform/gyms/{first['id']}/audit")
                assert response.status_code == 200
                events = response.json()
                assert len(events) == 1
                assert events[0]['event'] == 'gym_registered'
                assert client.get(f"/api/platform/gyms/{second['id']}/audit").json()[0]['id'] != events[0]['id']
                assert client.get('/api/platform/gyms/nonexistent/audit').status_code == 404
                app.dependency_overrides[get_clerk_claims] = lambda: {'sub': 'regular-gym-owner'}
                assert client.get(f"/api/platform/gyms/{first['id']}/audit").status_code == 403
        finally:
            app.dependency_overrides.clear()
    engine.dispose()
