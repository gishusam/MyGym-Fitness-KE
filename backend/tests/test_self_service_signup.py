from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.auth import get_clerk_claims
from backend.platform.app import PlatformBase, GymTenant, app, platform_db
from backend.platform import self_signup


def test_customer_signup_is_authenticated_verified_and_idempotent(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    user = {'sub':'user_customer_one'}
    app.dependency_overrides[get_clerk_claims] = lambda: user
    app.dependency_overrides[platform_db] = lambda: session
    monkeypatch.setattr(self_signup, 'get_settings', lambda: type('S', (), {'clerk_secret_key':'test-secret'})())
    monkeypatch.setattr(self_signup, 'get_verified_clerk_profile', lambda *args: ('Gym owner', {'owner@example.org'}))
    try:
        with TestClient(app) as client:
            assert client.get('/api/platform/signup/me').json() is None
            created = client.post('/api/platform/signup/gyms', json={'gym_name':'  Riverside  Fitness '})
            assert created.status_code == 201
            gym = created.json()
            assert gym['gym_name'] == 'Riverside Fitness'
            assert gym['status'] == 'pending_provisioning'
            again = client.post('/api/platform/signup/gyms', json={'gym_name':'Different Gym'})
            assert again.status_code == 201
            assert again.json()['id'] == gym['id']
            assert client.get('/api/platform/signup/me').json()['id'] == gym['id']
            assert session.scalar(select(func.count()).select_from(GymTenant)) == 1
            user['sub']='invalid_browser_user'
            assert client.post('/api/platform/signup/gyms', json={'gym_name':'Other Gym'}).status_code == 401
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_email_verification_is_required(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    session = Session(engine)
    app.dependency_overrides[get_clerk_claims] = lambda: {'sub':'user_unverified'}
    app.dependency_overrides[platform_db] = lambda: session
    monkeypatch.setattr(self_signup, 'get_settings', lambda: type('S', (), {'clerk_secret_key':'test-secret'})())
    monkeypatch.setattr(self_signup, 'get_verified_clerk_profile', lambda *args: ('Unknown', set()))
    try:
        with TestClient(app) as client:
            assert client.post('/api/platform/signup/gyms', json={'gym_name':'Test Gym'}).status_code == 403
            assert session.scalar(select(func.count()).select_from(GymTenant)) == 0
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
