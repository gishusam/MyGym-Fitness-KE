from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.auth import get_current_staff
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
import backend.app.api.routes.staff as staff_routes
from backend.app.models import (
    EventRegistration,
    GymEvent,
    GymSettings,
    Member,
    MembershipPlan,
    StaffRole,
    StaffUser,
    Subscription,
)
from backend.app.models.payment import Payment, PaymentStatus

NAIROBI = ZoneInfo("Africa/Nairobi")


def set_staff(staff: StaffUser) -> None:
    app.dependency_overrides[get_current_staff] = lambda: staff


def create_member(client: TestClient, phone: str) -> dict:
    response = client.post(
        "/api/members",
        json={"fullName": f"Member {phone[-4:]}", "phone": phone},
    )
    assert response.status_code == 201, response.text
    return response.json()


def workout_payload() -> dict:
    return {
        "name": "Strength Foundation",
        "goal": "Build consistent full-body strength",
        "description": "Three focused sessions each week.",
        "exercises": [
            {
                "name": "Goblet squat",
                "sets": 3,
                "repetitions": 10,
                "restSeconds": 60,
            }
        ],
    }


def event_payload(capacity: int = 1) -> dict:
    starts = datetime.now(NAIROBI).replace(second=0, microsecond=0) + timedelta(days=2)
    ends = starts + timedelta(hours=1)
    return {
        "name": "Saturday Strength Class",
        "description": "Small-group coaching.",
        "startsAt": starts.isoformat(),
        "endsAt": ends.isoformat(),
        "capacity": capacity,
        "status": "published",
    }


def test_role_permissions_for_new_workspaces(client: TestClient, staff_factory) -> None:
    trainer = staff_factory(StaffRole.TRAINER)
    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    member = create_member(client, "0712345601")
    owner_summary = client.get("/api/dashboard/summary")
    assert owner_summary.status_code == 200
    assert owner_summary.json()["role"] == "owner"
    assert client.get("/api/staff").status_code == 200
    event = client.post("/api/events", json=event_payload())
    assert event.status_code == 201, event.text

    set_staff(trainer)
    created = client.post("/api/workouts", json=workout_payload())
    assert created.status_code == 201, created.text
    assert created.json()["exercises"][0]["name"] == "Goblet squat"
    trainer_summary = client.get("/api/dashboard/summary")
    assert trainer_summary.status_code == 200
    assert trainer_summary.json()["role"] == "trainer"
    assert client.get("/api/trainer/members").status_code == 200
    assessment = client.post(
        f"/api/members/{member['id']}/fitness-assessments",
        json={"weightKg": 74, "heightCm": 178},
    )
    assert assessment.status_code == 201, assessment.text
    assert assessment.json()["bmi"] == 23.4
    assert client.get("/api/members").status_code == 403
    assert client.get("/api/payments").status_code == 403
    assert client.get("/api/gym-settings").status_code == 403
    assert client.patch(
        "/api/gym-settings",
        json={"gymName": "Not allowed"},
    ).status_code == 403

    set_staff(receptionist)
    receptionist_summary = client.get("/api/dashboard/summary")
    assert receptionist_summary.status_code == 200
    assert receptionist_summary.json()["role"] == "receptionist"
    assert client.get("/api/members").status_code == 200
    assert client.get("/api/payments").status_code == 200
    assert client.get("/api/gym-settings").status_code == 200
    assert client.get("/api/staff").status_code == 403
    assert client.get("/api/workouts").status_code == 403
    assert client.get("/api/trainer/members").status_code == 403
    assert client.post("/api/events", json=event_payload()).status_code == 403
    assert client.get("/api/events/members", params={"search": member["memberNumber"]}).status_code == 200
    registration = client.post(
        f"/api/events/{event.json()['id']}/registrations",
        json={"memberId": member["id"]},
    )
    assert registration.status_code == 201, registration.text
    app.dependency_overrides.clear()


def test_workout_assignment_and_private_resource_upload(
    client: TestClient,
    staff_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MYGYM_UPLOAD_DIR", str(tmp_path))
    trainer = staff_factory(StaffRole.TRAINER)
    member = create_member(client, "0712345602")
    set_staff(trainer)

    program = client.post("/api/workouts", json=workout_payload())
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]
    assigned = client.post(
        f"/api/workouts/{program_id}/assignments",
        json={"memberId": member["id"], "startsOn": datetime.now(NAIROBI).date().isoformat()},
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["memberId"] == member["id"]
    duplicate = client.post(
        f"/api/workouts/{program_id}/assignments",
        json={"memberId": member["id"], "startsOn": datetime.now(NAIROBI).date().isoformat()},
    )
    assert duplicate.status_code == 409
    cancelled_assignment = client.patch(
        f"/api/workout-assignments/{assigned.json()['id']}",
        json={"status": "cancelled"},
    )
    assert cancelled_assignment.status_code == 200
    replacement_assignment = client.post(
        f"/api/workouts/{program_id}/assignments",
        json={"memberId": member["id"], "startsOn": datetime.now(NAIROBI).date().isoformat()},
    )
    assert replacement_assignment.status_code == 201, replacement_assignment.text

    payload = b"%PDF-1.7\nMyGym trainer resource\n"
    upload = client.post(
        f"/api/workouts/{program_id}/resources",
        content=payload,
        headers={
            "content-type": "application/octet-stream",
            "x-file-name": "%2F..%2Fstrength-guide.pdf",
        },
    )
    assert upload.status_code == 201, upload.text
    resource = upload.json()
    assert resource["mediaType"] == "application/pdf"
    assert resource["sizeBytes"] == len(payload)
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1
    assert stored[0].stat().st_mode & 0o777 == 0o600

    download = client.get(resource["downloadUrl"])
    assert download.status_code == 200
    assert download.content == payload
    assert download.headers["cache-control"] == "private, no-store"

    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    set_staff(receptionist)
    assert client.get(resource["downloadUrl"]).status_code == 403
    app.dependency_overrides.clear()


def test_workout_upload_rejects_unrecognized_content(client: TestClient, staff_factory) -> None:
    trainer = staff_factory(StaffRole.TRAINER)
    set_staff(trainer)
    program = client.post("/api/workouts", json=workout_payload()).json()
    response = client.post(
        f"/api/workouts/{program['id']}/resources",
        content=b"<html>not an image or PDF</html>",
        headers={"content-type": "application/octet-stream", "x-file-name": "guide.pdf"},
    )
    assert response.status_code == 415
    app.dependency_overrides.clear()


def test_event_capacity_duplicate_and_re_registration(client: TestClient) -> None:
    first = create_member(client, "0712345603")
    second = create_member(client, "0712345604")
    created = client.post("/api/events", json=event_payload())
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    one = client.post(
        f"/api/events/{event_id}/registrations",
        json={"memberId": first["id"]},
    )
    assert one.status_code == 201, one.text
    duplicate = client.post(
        f"/api/events/{event_id}/registrations",
        json={"memberId": first["id"]},
    )
    assert duplicate.status_code == 409
    full = client.post(
        f"/api/events/{event_id}/registrations",
        json={"memberId": second["id"]},
    )
    assert full.status_code == 409
    assert full.json()["code"] == "event_capacity_reached"
    assert client.get(f"/api/events/{event_id}").json()["registeredCount"] == 1

    cancelled = client.delete(
        f"/api/events/{event_id}/registrations/{one.json()['id']}"
    )
    assert cancelled.status_code == 200
    assert client.get(f"/api/events/{event_id}").json()["registeredCount"] == 0
    replacement = client.post(
        f"/api/events/{event_id}/registrations",
        json={"memberId": second["id"]},
    )
    assert replacement.status_code == 201
    assert client.get(f"/api/events/{event_id}").json()["registeredCount"] == 1


def test_event_capacity_is_safe_for_concurrent_bookings(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-events.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions() as session:
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
        owner = StaffUser(
            name="Concurrent Test Owner",
            email="concurrent-owner@example.test",
            clerk_user_id="concurrent-test-owner",
            role=StaffRole.OWNER.value,
            status="active",
        )
        first = Member(
            member_number="MG-CONCURRENT-01",
            full_name="First Concurrent Member",
            phone="0712345691",
            qr_token="concurrent-member-qr-1",
        )
        second = Member(
            member_number="MG-CONCURRENT-02",
            full_name="Second Concurrent Member",
            phone="0712345692",
            qr_token="concurrent-member-qr-2",
        )
        starts = datetime.now(NAIROBI).replace(second=0, microsecond=0) + timedelta(days=2)
        event = GymEvent(
            name="Concurrent Capacity Check",
            starts_at=starts.astimezone(ZoneInfo("UTC")),
            ends_at=(starts + timedelta(hours=1)).astimezone(ZoneInfo("UTC")),
            capacity=1,
            status="published",
            created_by_staff_id=owner.id,
        )
        session.add_all([owner, first, second, event])
        session.commit()
        owner_id = owner.id
        event_id = event.id
        member_ids = [first.id, second.id]

    detached_owner = StaffUser(
        id=owner_id,
        name="Concurrent Test Owner",
        email="concurrent-owner@example.test",
        clerk_user_id="concurrent-test-owner",
        role=StaffRole.OWNER.value,
        status="active",
    )
    app.dependency_overrides[get_current_staff] = lambda: detached_owner

    def override_db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    start_together = Barrier(2)

    def register(member_id) -> tuple[int, dict]:
        with TestClient(app) as test_client:
            start_together.wait(timeout=5)
            response = test_client.post(
                f"/api/events/{event_id}/registrations",
                json={"memberId": str(member_id)},
            )
            return response.status_code, response.json()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, member_ids))
        assert sorted(status for status, _body in results) == [201, 409], results
        rejected = next(body for status, body in results if status == 409)
        assert rejected["code"] == "event_capacity_reached"
        with sessions() as session:
            saved_event = session.get(GymEvent, event_id)
            registration_count = session.scalar(
                select(func.count())
                .select_from(EventRegistration)
                .where(
                    EventRegistration.event_id == event_id,
                    EventRegistration.status == "confirmed",
                )
            )
            assert saved_event.confirmed_count == 1
            assert registration_count == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_owner_dashboard_uses_real_payment_data_and_protects_last_owner(
    client: TestClient, db: Session, staff_factory
) -> None:
    owner = app.dependency_overrides[get_current_staff]()
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["role"] == "owner"
    assert summary["activeMembers"] == 0
    assert summary["paymentsThisMonth"] == 0
    assert summary["revenueThisMonthKes"] is None
    assert summary["membershipsExpiringCount"] == 0
    assert summary["expiredMembers"] == 0
    assert len(summary["revenueTrend"]) == datetime.now(NAIROBI).date().day
    assert sum(day["amountKes"] for day in summary["revenueTrend"]) == 0

    member = create_member(client, "0712345699")
    member_id = UUID(member["id"])
    today = datetime.now(NAIROBI).date()
    plan = MembershipPlan(name="Dashboard Test Plan", monthly_price_kes=4200, is_active=True)
    db.add(plan)
    db.flush()
    db.add(
        Subscription(
            member_id=member_id,
            plan_id=plan.id,
            plan_name=plan.name,
            monthly_price_kes=plan.monthly_price_kes,
            starts_on=today - timedelta(days=40),
            expires_on=today - timedelta(days=1),
            status="active",
        )
    )
    db.commit()
    assert client.get("/api/dashboard/summary").json()["expiredMembers"] == 1
    db.add(
        Subscription(
            member_id=member_id,
            plan_id=plan.id,
            plan_name=plan.name,
            monthly_price_kes=plan.monthly_price_kes,
            starts_on=today,
            expires_on=today + timedelta(days=3),
            status="active",
        )
    )
    paid_at = (datetime.now(NAIROBI) - timedelta(minutes=1)).astimezone(timezone.utc)
    db.add(
        Payment(
            member_id=member_id,
            amount_kes=4200,
            method="cash",
            status=PaymentStatus.RECORDED.value,
            paid_at=paid_at,
        )
    )
    db.commit()
    updated_summary = client.get("/api/dashboard/summary").json()
    today_revenue = next(
        day for day in updated_summary["revenueTrend"]
        if day["day"] == paid_at.astimezone(NAIROBI).date().isoformat()
    )
    assert updated_summary["revenueThisMonthKes"] == 4200
    assert updated_summary["expiredMembers"] == 0
    assert updated_summary["membershipsExpiringCount"] == 1
    assert updated_summary["membershipsExpiring"][0]["phone"] == member["phone"]
    assert today_revenue["amountKes"] == 4200

    rejected = client.patch(
        f"/api/staff/{owner.id}",
        json={"status": "inactive"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "last_active_owner"

    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    set_staff(receptionist)
    forbidden = client.get("/api/staff")
    assert forbidden.status_code == 403
    assert client.patch(
        f"/api/staff/{owner.id}",
        json={"role": "trainer"},
    ).status_code == 403
    trainer = staff_factory(StaffRole.TRAINER)
    set_staff(trainer)
    trainer_summary = client.get("/api/dashboard/summary").json()
    assert trainer_summary["membershipsExpiring"] == []
    assert trainer_summary["expiredMembers"] is None
    assert trainer_summary["revenueTrend"] == []
    app.dependency_overrides.clear()


def test_only_owner_can_assign_a_verified_staff_account(
    client: TestClient, staff_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        staff_routes,
        "get_settings",
        lambda: SimpleNamespace(clerk_secret_key="configured-for-test"),
    )
    monkeypatch.setattr(
        staff_routes,
        "find_verified_clerk_user_by_email",
        lambda email, _secret: ("clerk-verified-trainer", "Verified Trainer"),
    )

    created = client.post(
        "/api/staff",
        json={"email": "trainer@example.test", "role": "trainer"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "trainer@example.test"
    assert created.json()["role"] == "trainer"
    duplicate = client.post(
        "/api/staff",
        json={"email": "trainer@example.test", "role": "receptionist"},
    )
    assert duplicate.status_code == 409

    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    set_staff(receptionist)
    forbidden = client.post(
        "/api/staff",
        json={"email": "another@example.test", "role": "receptionist"},
    )
    assert forbidden.status_code == 403
    app.dependency_overrides.clear()
