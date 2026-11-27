"""Public onboarding links must route to only the registered gym whose ID is supplied."""
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db import tenant_sessions
from backend.app.main import app
from backend.app.models.member import Member
from backend.app.models.member_onboarding import MemberOnboardingToken, MemberFitnessProfile
from backend.app.models.member_workout_link import MemberWorkoutLink
from backend.app.models.membership import MembershipPlan, Subscription
from backend.app.models.workout import WorkoutProgram, WorkoutAssignment
from backend.platform.app import GymTenant, PlatformBase


@pytest.fixture
def gyms(monkeypatch):
    def memory_db():
        return create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    platform_e, mygym_e, demo_e = memory_db(), memory_db(), memory_db()
    PlatformBase.metadata.create_all(platform_e)
    Base.metadata.create_all(mygym_e)
    Base.metadata.create_all(demo_e)
    platform_factory = sessionmaker(bind=platform_e, expire_on_commit=False)
    fixtures = [
        GymTenant(id=str(uuid4()), slug='mygym-t', name='MyGym', environment_kind='development',
                  database_ref='mygym_fitness_dev', status='active'),
        GymTenant(id=str(uuid4()), slug='demofit-t', name='DemoFit', environment_kind='demo',
                  database_ref='mygym_demo', status='active'),
    ]
    with platform_factory() as db:
        db.add_all(fixtures)
        db.commit()
    factories = {'mygym_fitness_dev': sessionmaker(bind=mygym_e, expire_on_commit=False),
                 'mygym_demo': sessionmaker(bind=demo_e, expire_on_commit=False)}
    monkeypatch.setattr('backend.platform.app.platform_session_factory', lambda: platform_factory)
    monkeypatch.setattr(tenant_sessions, 'existing_factory', lambda name: factories[name])
    app.dependency_overrides.clear()
    try:
        with TestClient(app) as client:
            yield client, fixtures, factories
    finally:
        app.dependency_overrides.clear()
        for engine in (platform_e, mygym_e, demo_e):
            engine.dispose()


def member_token(factory, expires_at=None):
    token = 'test-' + uuid4().hex
    with factory() as db:
        member = Member(id=uuid4(), member_number='M'+uuid4().hex[:12], full_name='Demo Member',
                        phone='07'+str(uuid4().int)[-8:], qr_token=uuid4().hex, status='active')
        db.add(member)
        db.flush()
        db.add(MemberOnboardingToken(member_id=member.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                    expires_at=expires_at or datetime.now(timezone.utc)+timedelta(days=1)))
        db.commit()
        return token, member.id


def test_public_link_opens_without_clerk_cookie(gyms):
    client, fixture, factory = gyms
    token, _ = member_token(factory['mygym_demo'])
    result = client.get(f'/api/public/onboarding/{token}?gym={fixture[1].id}')
    assert result.status_code == 200, result.text
    assert result.json()['firstName'] == 'Demo'


def test_wrong_gym_or_missing_gym_is_not_authorized(gyms):
    client, fixture, factory = gyms
    token, _ = member_token(factory['mygym_demo'])
    assert client.get(f'/api/public/onboarding/{token}?gym={fixture[0].id}').status_code == 404
    assert client.get(f'/api/public/onboarding/{token}').status_code == 404
    assert client.get(f'/api/public/onboarding/{token}?gym=not-a-uuid').status_code == 404


def test_expired_token_is_denied(gyms):
    client, fixture, factory = gyms
    token, _ = member_token(factory['mygym_demo'], expires_at=datetime.now(timezone.utc)-timedelta(seconds=2))
    assert client.get(f'/api/public/onboarding/{token}?gym={fixture[1].id}').status_code == 404


def test_submission_writes_only_to_selected_gym(gyms):
    client, fixture, factory = gyms
    token, member_id = member_token(factory['mygym_demo'])
    result = client.post(f'/api/public/onboarding/{token}?gym={fixture[1].id}', json={
        'primaryGoal': 'build_strength', 'experience': 'beginner',
        'availableDaysPerWeek': 3, 'sessionDurationMinutes': 45,
        'equipmentPreferences': [], 'limitations': None, 'notes': None,
    })
    assert result.status_code == 200, result.text
    with factory['mygym_demo']() as db:
        assert db.scalar(select(MemberFitnessProfile).where(MemberFitnessProfile.member_id==member_id)) is not None
    with factory['mygym_fitness_dev']() as db:
        assert db.scalar(select(MemberFitnessProfile)) is None


def test_workout_link_and_pdf_are_scoped_to_one_gym(gyms):
    client, fixture, factory = gyms
    token, member_id = member_token(factory['mygym_demo'])
    raw = 'workout-' + uuid4().hex
    today = datetime.now(ZoneInfo('Africa/Nairobi')).date()
    with factory['mygym_demo']() as db:
        program = WorkoutProgram(id=uuid4(), name='Member Program', goal='Fitness',
                                 recommended_days_per_week=3, expected_session_minutes=45)
        plan = MembershipPlan(id=uuid4(), name='Member Plan', monthly_price_kes=4000, is_active=True)
        db.add_all([program, plan])
        db.flush()
        assignment = WorkoutAssignment(id=uuid4(), program_id=program.id, member_id=member_id,
                                       starts_on=today, status='assigned')
        subscription = Subscription(id=uuid4(), member_id=member_id, plan_id=plan.id,
                                    plan_name='Member Plan', monthly_price_kes=4000,
                                    starts_on=today-timedelta(days=1), expires_on=today+timedelta(days=30), status='active')
        db.add_all([assignment, subscription])
        db.flush()
        db.add(MemberWorkoutLink(assignment_id=assignment.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                                 expires_at=datetime.now(timezone.utc)+timedelta(days=5)))
        db.commit()
    url = f'/api/public/workout/{raw}'
    assert client.get(f'{url}?gym={fixture[0].id}').status_code == 404
    allowed = client.get(f'{url}?gym={fixture[1].id}')
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()['memberName'] == 'Demo Member'
    pdf = client.get(f'{url}/pdf?gym={fixture[1].id}')
    assert pdf.status_code == 200
    assert pdf.content.startswith(b'%PDF-')
    with factory['mygym_demo']() as db:
        db.execute(update(MemberWorkoutLink).values(revoked_at=datetime.now(timezone.utc)))
        db.commit()
    assert client.get(f'{url}?gym={fixture[1].id}').status_code == 404
