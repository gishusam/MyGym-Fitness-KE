from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.config import AppSettings
from backend.app.core.auth import get_clerk_claims, get_current_member, get_member_db
from backend.app.main import app
from backend.app.models.attendance import CheckIn
from backend.app.models.audit_log import AuditLog
from backend.app.models.fitness_assessment import FitnessAssessment
from backend.app.models.gym_event import EventRegistration, GymEvent
from backend.app.models.member import Member
from backend.app.models.workout import (
    WorkoutAssignment,
    WorkoutExercise,
    WorkoutProgram,
    WorkoutSession,
)
from backend.app.services.operations import gym_now


def make_member(db, *, name: str, email: str | None = None) -> Member:
    member = Member(
        id=uuid4(),
        member_number=f"MG-{uuid4().hex[:10].upper()}",
        full_name=name,
        phone=f"07{uuid4().int % 10**8:08d}",
        email=email,
        qr_token=uuid4().hex,
        status="active",
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def make_assignment(db, member: Member) -> tuple[WorkoutAssignment, WorkoutExercise]:
    program = WorkoutProgram(
        id=uuid4(),
        name="Strength Basics",
        goal="Build strength",
        goals_supported=["build_strength"],
        minimum_experience="beginner",
        maximum_experience="advanced",
        recommended_days_per_week=3,
        expected_session_minutes=45,
        equipment_requirements=[],
        trainer_review_required=False,
        status="active",
    )
    db.add(program)
    db.flush()
    exercise = WorkoutExercise(
        id=uuid4(),
        program_id=program.id,
        position=0,
        name="Goblet squat",
        sets=3,
        repetitions=10,
        rest_seconds=60,
    )
    assignment = WorkoutAssignment(
        id=uuid4(),
        program_id=program.id,
        member_id=member.id,
        starts_on=gym_now(db).date(),
        status="assigned",
    )
    db.add_all([exercise, assignment])
    db.commit()
    db.refresh(assignment)
    return assignment, exercise


def test_member_portal_requires_member_authentication(client):
    response = client.get("/api/member/me")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_member_api_does_not_require_staff_workspace_cookie(client, db):
    member = make_member(db, name="Mobile Member")
    member.clerk_user_id = "user_member_mobile"
    db.commit()
    app.dependency_overrides[get_clerk_claims] = lambda: {
        "sub": "user_member_mobile",
        "azp": "https://native.example.test",
    }
    app.dependency_overrides[get_member_db] = lambda: db

    response = client.get("/api/member/me")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(member.id)


def test_member_profile_and_workouts_are_scoped_and_persisted(client, db):
    current_member = make_member(db, name="Amina Member")
    other_member = make_member(db, name="Other Member")
    own_assignment, own_exercise = make_assignment(db, current_member)
    other_assignment, other_exercise = make_assignment(db, other_member)
    app.dependency_overrides[get_current_member] = lambda: current_member
    app.dependency_overrides[get_member_db] = lambda: db

    profile = client.get("/api/member/me")
    assert profile.status_code == 200, profile.text
    assert profile.json()["id"] == str(current_member.id)
    assert profile.json()["fullName"] == "Amina Member"
    assert profile.json()["qrToken"] == current_member.qr_token

    workouts = client.get("/api/member/workouts")
    assert workouts.status_code == 200, workouts.text
    assert [item["id"] for item in workouts.json()] == [str(own_assignment.id)]
    assert workouts.json()[0]["exercises"][0]["name"] == "Goblet squat"

    foreign_session = client.post(
        f"/api/member/workouts/{other_assignment.id}/sessions",
        json={
            "exercises": [
                {
                    "exerciseId": str(other_exercise.id),
                    "completed": True,
                }
            ]
        },
    )
    assert foreign_session.status_code == 404

    saved = client.post(
        f"/api/member/workouts/{own_assignment.id}/sessions",
        json={
            "exercises": [
                {
                    "exerciseId": str(own_exercise.id),
                    "completed": True,
                    "weightKg": 16,
                    "repsCompleted": 10,
                }
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "completed"
    assert saved.json()["exercises"][0]["weightKg"] == 16
    assert db.scalar(select(WorkoutAssignment).where(WorkoutAssignment.id == own_assignment.id)).status == "completed"
    assert db.scalar(
        select(func.count(WorkoutSession.id)).where(
            WorkoutSession.member_id == current_member.id
        )
    ) == 1

    fetched = client.get("/api/member/workouts").json()[0]
    assert len(fetched["sessions"]) == 1
    assert fetched["sessions"][0]["id"] == saved.json()["id"]


def test_member_event_self_registration_is_capacity_safe_and_cancellable(client, db):
    current_member = make_member(db, name="Event Member")
    other_member = make_member(db, name="Second Event Member")
    now = datetime.now(timezone.utc)
    event = GymEvent(
        id=uuid4(),
        name="Saturday Mobility",
        description="Member mobility session",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=1),
        capacity=1,
        confirmed_count=0,
        status="published",
    )
    db.add(event)
    db.commit()
    app.dependency_overrides[get_current_member] = lambda: current_member
    app.dependency_overrides[get_member_db] = lambda: db

    events = client.get("/api/member/events")
    assert events.status_code == 200, events.text
    assert events.json()[0]["registrationStatus"] is None

    registration = client.post(f"/api/member/events/{event.id}/registration")
    assert registration.status_code == 201, registration.text
    assert registration.json()["memberId"] == str(current_member.id)
    assert db.get(GymEvent, event.id).confirmed_count == 1
    assert client.get("/api/member/events").json()[0]["registrationStatus"] == "confirmed"
    duplicate = client.post(f"/api/member/events/{event.id}/registration")
    assert duplicate.status_code == 409

    app.dependency_overrides[get_current_member] = lambda: other_member
    full = client.post(f"/api/member/events/{event.id}/registration")
    assert full.status_code == 409
    assert full.json()["code"] == "event_capacity_reached"

    app.dependency_overrides[get_current_member] = lambda: current_member
    cancelled = client.delete(f"/api/member/events/{event.id}/registration")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert db.get(GymEvent, event.id).confirmed_count == 0
    assert client.get("/api/member/events").json()[0]["registrationStatus"] == "cancelled"
    assert db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "event.member_self_registered"
        )
    ) == 1


def test_member_progress_only_returns_own_records(client, db):
    current_member = make_member(db, name="Progress Member")
    other_member = make_member(db, name="Other Progress Member")
    own_assignment, _ = make_assignment(db, current_member)
    other_assignment, _ = make_assignment(db, other_member)
    today = gym_now(db).date()

    own_assessment = FitnessAssessment(
        id=uuid4(),
        member_id=current_member.id,
        recorded_at=datetime.now(timezone.utc),
        weight_kg=72,
        height_cm=170,
        bmi=24.9,
    )
    other_assessment = FitnessAssessment(
        id=uuid4(),
        member_id=other_member.id,
        recorded_at=datetime.now(timezone.utc),
        weight_kg=99,
        height_cm=180,
        bmi=30.6,
    )
    db.add_all(
        [
            own_assessment,
            other_assessment,
            CheckIn(member_id=current_member.id, checked_in_at=datetime.now(timezone.utc)),
            CheckIn(member_id=other_member.id, checked_in_at=datetime.now(timezone.utc)),
            WorkoutSession(
                assignment_id=own_assignment.id,
                member_id=current_member.id,
                session_date=today,
                status="completed",
                exercises=[],
            ),
            WorkoutSession(
                assignment_id=other_assignment.id,
                member_id=other_member.id,
                session_date=today,
                status="completed",
                exercises=[],
            ),
        ]
    )
    db.commit()
    app.dependency_overrides[get_current_member] = lambda: current_member
    app.dependency_overrides[get_member_db] = lambda: db

    progress = client.get("/api/member/progress")
    assert progress.status_code == 200, progress.text
    payload = progress.json()
    assert [item["id"] for item in payload["assessments"]] == [str(own_assessment.id)]
    assert payload["checkInsThisMonth"] == 1
    assert payload["workoutsThisMonth"] == 1


def test_first_member_link_uses_only_verified_email(client, db, monkeypatch):
    member = make_member(db, name="Verified Email Member", email="member@example.test")
    monkeypatch.setattr(
        "backend.app.core.auth.get_verified_clerk_profile",
        lambda _user_id, _secret: ({}, {"member@example.test"}),
    )

    linked = get_current_member(
        {"sub": "user_mobile_verified"},
        db,
        AppSettings(clerk_secret_key="test-only"),
    )
    assert linked.id == member.id
    assert linked.clerk_user_id == "user_mobile_verified"

    unverified_member = make_member(
        db, name="Unverified Email Member", email="unverified@example.test"
    )
    monkeypatch.setattr(
        "backend.app.core.auth.get_verified_clerk_profile",
        lambda _user_id, _secret: ({}, set()),
    )
    with pytest.raises(HTTPException) as error:
        get_current_member(
            {"sub": "user_without_verified_email"},
            db,
            AppSettings(clerk_secret_key="test-only"),
        )
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "member_account_unlinked"
    assert unverified_member.clerk_user_id is None


def test_first_member_link_rejects_ambiguous_verified_email(client, db, monkeypatch):
    first = make_member(db, name="Duplicate Email One", email="duplicate@example.test")
    second = make_member(db, name="Duplicate Email Two", email="duplicate@example.test")
    monkeypatch.setattr(
        "backend.app.core.auth.get_verified_clerk_profile",
        lambda _user_id, _secret: ({}, {"duplicate@example.test"}),
    )

    with pytest.raises(HTTPException) as error:
        get_current_member(
            {"sub": "user_ambiguous_email"},
            db,
            AppSettings(clerk_secret_key="test-only"),
        )
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "member_account_unlinked"
    assert first.clerk_user_id is None
    assert second.clerk_user_id is None
