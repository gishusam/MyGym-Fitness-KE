from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.auth import get_current_staff
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models import GymSettings, StaffRole, StaffStatus, StaffUser


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(_type, _compiler, **_kw) -> str:
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kw) -> str:
    return "JSON"


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = Session(engine, autoflush=False, expire_on_commit=False)
    session.add(
        GymSettings(
            id=1,
            gym_name="MyGym Fitness KE",
            timezone="Africa/Nairobi",
            currency="KES",
            attendance_duplicate_interval_minutes=5,
            inactivity_threshold_days=14,
            renewal_reminder_days_before=3,
            peak_access_hours_configured=False,
            owner_bootstrap_completed=True,
        )
    )
    session.commit()
    yield session
    session.close()


@pytest.fixture
def staff_factory(db: Session):
    def create(role: StaffRole | str) -> StaffUser:
        staff = StaffUser(
            id=uuid4(),
            clerk_user_id=f"clerk-{uuid4()}",
            name=f"Test {role}",
            email=f"{role}-{uuid4()}@example.test",
            role=str(role),
            status=StaffStatus.ACTIVE.value,
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        return staff

    return create


@pytest.fixture
def client(db: Session, staff_factory) -> Iterator[TestClient]:
    current_staff = staff_factory(StaffRole.OWNER)
    app.dependency_overrides[get_current_staff] = lambda: current_staff

    def override_db() -> Iterator[Session]:
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
