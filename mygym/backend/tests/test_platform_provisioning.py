from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url

from backend.app.core.auth import get_clerk_claims
from backend.platform.app import PlatformAudit, PlatformBase, GymTenant, app, platform_db, platform_session_factory
from backend.platform.credentials import decrypt_database_url
from backend.platform.provisioning import (
    _prepare_tenant_url,
    database_role_for_slug,
    db_name_for_slug,
    provision,
)


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
    assert database_role_for_slug("fit-zone") == database_role_for_slug("fit-zone")
    assert database_role_for_slug("fit-zone") != database_role_for_slug("other-gym")


def test_new_tenant_url_uses_dedicated_role_and_is_encrypted(monkeypatch):
    import base64

    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    monkeypatch.setenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", key)
    gym = GymTenant(id="gym-a", name="Gym A", slug="gym-a")

    admin_url, tenant_url, role, ciphertext = _prepare_tenant_url(
        gym,
        db_name="mygym_tenant_gym_a",
        admin_url="postgresql+psycopg://operator:operator-password@db.example:5432/postgres",
        platform_url="postgresql+psycopg://platform:platform-password@db.example:5432/mygym_platform",
    )

    assert admin_url.endswith("/postgres")
    parsed = make_url(tenant_url)
    assert parsed.username == role == database_role_for_slug("gym-a")
    assert parsed.database == "mygym_tenant_gym_a"
    assert parsed.password
    assert ciphertext != tenant_url
    assert parsed.password not in ciphertext
    gym.database_url_ciphertext = ciphertext
    assert _prepare_tenant_url(
        gym,
        db_name="mygym_tenant_gym_a",
        admin_url=admin_url,
        platform_url="postgresql+psycopg://platform:platform-password@db.example:5432/mygym_platform",
    ) == (admin_url, tenant_url, role, ciphertext)


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


def test_apply_requires_encryption_key_before_changing_registry(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}")
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as session:
        gym = GymTenant(id=str(uuid4()), name="Gym A", slug="gym-a")
        session.add(gym)
        session.commit()
        gym_id = gym.id

    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(
        "backend.platform.provisioning.platform_session_factory",
        lambda: sessionmaker(bind=engine, expire_on_commit=False),
    )
    monkeypatch.setenv(
        "GYM_PROVISION_ADMIN_URL",
        "postgresql+psycopg://operator:operator-password@db.example:5432/postgres",
    )
    monkeypatch.setenv(
        "PLATFORM_DATABASE_URL",
        "postgresql+psycopg://platform:platform-password@db.example:5432/mygym_platform",
    )
    monkeypatch.delenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", raising=False)

    with pytest.raises(ValueError, match="PLATFORM_CREDENTIAL_ENCRYPTION_KEYS must be configured"):
        provision(gym_id, apply=True)

    with Session(engine) as session:
        gym = session.get(GymTenant, gym_id)
        assert gym.status == "pending_provisioning"
        assert gym.database_url_ciphertext is None
        assert session.scalars(select(PlatformAudit)).all() == []
    engine.dispose()


def test_provision_creates_isolated_role_and_sanitizes_migration_environment(
    monkeypatch, tmp_path
):
    import base64
    import psycopg
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}")
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        gym = GymTenant(id=str(uuid4()), name="Gym A", slug="gym-a")
        session.add(gym)
        session.commit()
        gym_id = gym.id
    monkeypatch.setattr(
        "backend.platform.provisioning.platform_session_factory", lambda: factory
    )
    monkeypatch.setenv(
        "GYM_PROVISION_ADMIN_URL",
        "postgresql+psycopg://operator:operator-password@db.example:5432/postgres",
    )
    monkeypatch.setenv(
        "PLATFORM_DATABASE_URL",
        "postgresql+psycopg://platform:platform-password@db.example:5432/mygym_platform",
    )
    monkeypatch.setenv(
        "PLATFORM_CREDENTIAL_ENCRYPTION_KEYS",
        base64.urlsafe_b64encode(b"k" * 32).decode("ascii"),
    )
    monkeypatch.setenv("CLERK_SECRET_KEY", "test-only-clerk-secret")
    monkeypatch.setenv("PAYMENTS_SECRET_KEY", "test-only-payments-secret")
    monkeypatch.setenv("UNRELATED_RUNTIME_VALUE", "test-only-value")

    statements = []

    class FakeResult:
        def __init__(self, row=None, scalar=None):
            self.row = row
            self.scalar = scalar

        def fetchone(self):
            return self.row

        def scalar_one(self):
            return self.scalar

    class FakeAdminConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, params=None):
            statements.append((query, params))
            statement = str(query)
            if "FROM pg_roles" in statement:
                return FakeResult()
            if "SELECT 1 FROM pg_database" in statement:
                return FakeResult()
            if "information_schema.tables" in statement:
                return FakeResult(scalar=3)
            return FakeResult()

    class FakeVerifyEngine:
        def connect(self):
            return FakeAdminConnection()

        def dispose(self):
            return None

    migration_environment = {}
    migration_working_directory = {}

    def fake_subprocess_run(_command, *, cwd, env, check):
        migration_environment.update(env)
        migration_working_directory.update(path=cwd, exists=Path(cwd).exists())

    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda *_args, **_kwargs: FakeAdminConnection(),
    )
    monkeypatch.setattr(
        "backend.platform.provisioning.subprocess.run",
        fake_subprocess_run,
    )
    monkeypatch.setattr(
        "backend.platform.provisioning.create_engine",
        lambda *_args, **_kwargs: FakeVerifyEngine(),
    )

    assert provision(gym_id, apply=True) == "mygym_tenant_gym_a"

    with factory() as session:
        gym = session.get(GymTenant, gym_id)
        assert gym.status == "awaiting_owner"
        assert gym.database_ref == "mygym_tenant_gym_a"
        tenant_url = decrypt_database_url(gym.database_url_ciphertext)
        assert make_url(tenant_url).username == database_role_for_slug("gym-a")
        assert [
            event.event for event in session.scalars(select(PlatformAudit)).all()
        ] == ["provisioning_started", "database_provisioned"]

    if set(migration_environment) - {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TZ",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "DATABASE_URL",
    }:
        pytest.fail("Unexpected environment variables reached the migration subprocess")
    if "DATABASE_URL" not in migration_environment:
        pytest.fail("Tenant database URL was not passed to the migration subprocess")
    if not migration_working_directory.get("exists"):
        pytest.fail("Migration subprocess was not given an isolated working directory")
    if Path(migration_working_directory["path"], ".env").exists():
        pytest.fail("Migration subprocess could reload a project .env file")
    assert statements
    engine.dispose()
