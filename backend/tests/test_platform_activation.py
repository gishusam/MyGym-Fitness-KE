from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.platform.app import app, GymTenant, PlatformAudit, PlatformBase, platform_db, require_platform_admin
from backend.platform.activation import GymActivationError, GymVerification, verify_linked_gym
import backend.platform.activation as activation


def test_activate_linked_gym_and_idempotency(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(GymTenant(id='demo-id', slug='demofit-studio', name='DemoFit Studio', database_ref='mygym_demo', environment_kind='demo', status='linked'))
        db.add(GymTenant(id='dev-id', slug='mygym-fitness-ke', name='MyGym Fitness KE', database_ref='mygym_fitness_dev', environment_kind='development', status='linked'))
        db.commit()
    calls = []
    def fake_verify(alias):
        calls.append(alias)
        name = 'DemoFit Studio · DEMO DATA' if alias == 'mygym_demo' else 'MyGym Fitness KE'
        return GymVerification(alias, name, 'user_owner_one')
    monkeypatch.setattr(activation, 'verify_linked_gym', fake_verify)
    app.dependency_overrides[platform_db] = lambda: factory()
    app.dependency_overrides[require_platform_admin] = lambda: 'user_platform_admin'
    try:
        with TestClient(app) as client:
            for gym_id in ('demo-id', 'dev-id'):
                response = client.post(f'/api/platform/gyms/{gym_id}/verify-activate')
                assert response.status_code == 200, response.text
                assert response.json()['status'] == 'active'
                assert response.json()['ownerClerkUserId'] == 'user_owner_one'
                assert client.post(f'/api/platform/gyms/{gym_id}/verify-activate').status_code == 200
            with factory() as db:
                assert len(db.scalars(select(PlatformAudit)).all()) == 2
            assert calls == ['mygym_demo','mygym_demo','mygym_fitness_dev','mygym_fitness_dev']
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_activation_refuses_unlinked_or_mismatched_owner(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(GymTenant(id='linked', name='MyGym Fitness KE', slug='mygym-fitness-ke', database_ref='mygym_fitness_dev', environment_kind='development', status='linked', owner_clerk_user_id='user_other'))
        db.add(GymTenant(id='pending', name='Pending', slug='pending'))
        db.commit()
    monkeypatch.setattr(activation, 'verify_linked_gym', lambda alias: GymVerification(alias,'MyGym Fitness KE','user_owner_one'))
    app.dependency_overrides[platform_db] = lambda: factory()
    app.dependency_overrides[require_platform_admin] = lambda: 'user_admin'
    try:
        with TestClient(app) as client:
            assert client.post('/api/platform/gyms/pending/verify-activate').status_code == 409
            response = client.post('/api/platform/gyms/linked/verify-activate')
            assert response.status_code == 409
            assert response.json()['detail']['code'] == 'gym_owner_mismatch'
            assert client.post('/api/platform/gyms/missing/verify-activate').status_code == 404
        with factory() as db:
            assert db.get(GymTenant,'linked').status == 'linked'
            assert db.get(GymTenant,'linked').owner_clerk_user_id == 'user_other'
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_fail_closed_for_unknown_database(monkeypatch):
    monkeypatch.setenv('GYM_SOURCE_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_fitness_dev')
    monkeypatch.setenv('PLATFORM_DATABASE_URL', 'postgresql+psycopg://fake@localhost/mygym_platform')
    try:
        verify_linked_gym('arbitrary_customer_database')
        assert False, 'Expected failure'
    except GymActivationError as e:
        assert 'not configured' in str(e)
