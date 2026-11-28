from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import tenant_sessions
from backend.platform import app as platform_app


def _registry_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    platform_app.PlatformBase.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_fixed_member_session_uses_only_configured_active_gym(monkeypatch):
    registry_engine, registry_factory = _registry_factory()
    gym_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    gym_factory = sessionmaker(bind=gym_engine, expire_on_commit=False)
    gym_id = str(uuid4())
    with registry_factory() as registry:
        registry.add(
            platform_app.GymTenant(
                id=gym_id,
                slug="mygym-single",
                name="MyGym Fitness KE",
                environment_kind="development",
                database_ref="mygym_fitness_dev",
                status="active",
            )
        )
        registry.commit()

    monkeypatch.setattr(
        platform_app, "platform_session_factory", lambda: registry_factory
    )
    monkeypatch.setattr(
        tenant_sessions,
        "existing_factory",
        lambda database_name: gym_factory
        if database_name == "mygym_fitness_dev"
        else pytest.fail("Unexpected database mapping"),
    )

    session = tenant_sessions.resolve_member_session(gym_id)
    try:
        assert session.get_bind() is gym_engine
    finally:
        session.close()
        registry_engine.dispose()
        gym_engine.dispose()


def test_fixed_member_session_fails_closed_without_active_gym(monkeypatch):
    registry_engine, registry_factory = _registry_factory()
    gym_id = str(uuid4())
    with registry_factory() as registry:
        registry.add(
            platform_app.GymTenant(
                id=gym_id,
                slug="mygym-paused",
                name="Paused Gym",
                environment_kind="development",
                database_ref="mygym_fitness_dev",
                status="suspended",
            )
        )
        registry.commit()
    monkeypatch.setattr(
        platform_app, "platform_session_factory", lambda: registry_factory
    )
    monkeypatch.setattr(
        tenant_sessions,
        "existing_factory",
        lambda _database_name: pytest.fail("Inactive gym must not be opened"),
    )

    with pytest.raises(HTTPException) as error:
        tenant_sessions.resolve_member_session(gym_id)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "member_portal_unavailable"
    registry_engine.dispose()


def test_fixed_member_session_requires_server_configuration():
    with pytest.raises(HTTPException) as error:
        tenant_sessions.resolve_member_session(None)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "member_portal_unavailable"
