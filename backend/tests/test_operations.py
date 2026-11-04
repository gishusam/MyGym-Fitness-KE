from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from backend.app.api.routes import operations
from backend.app.core.auth import get_current_staff
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models import (
    AuditLog,
    CheckIn,
    GymSettings,
    Member,
    MembershipPlan,
    Payment,
    PlanAccessWindow,
    StaffRole,
    StaffUser,
    Subscription,
)
from backend.app.services.operations import next_calendar_month

NAIROBI = ZoneInfo("Africa/Nairobi")


def fixed_now(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=NAIROBI)


def member_payload(name: str = "Sam Member", phone: str = "0712345678") -> dict:
    return {"fullName": name, "phone": phone, "email": None}


def create_member(client: TestClient, phone: str = "0712345678") -> dict:
    response = client.post("/api/members", json=member_payload(phone=phone))
    assert response.status_code == 201, response.text
    return response.json()


def create_plan(
    client: TestClient,
    *,
    name: str = "Off-Peak",
    active: bool = True,
    windows: list[dict] | None = None,
) -> dict:
    if windows is None:
        windows = [
            {"weekday": weekday, "startsAt": "09:00", "endsAt": "15:00"}
            for weekday in range(7)
        ]
    response = client.post(
        "/api/membership-plans",
        json={
            "name": name,
            "monthlyPriceKes": 4000 if name == "Off-Peak" else 5000,
            "isActive": active,
            "accessWindows": windows,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def subscribe(
    client: TestClient, member_id: str, plan_id: str, starts_on: str = "2024-01-31"
) -> TestClient:
    return client.post(
        f"/api/members/{member_id}/subscriptions",
        json={"planId": plan_id, "startsOn": starts_on},
    )


def set_staff(client: TestClient, staff: StaffUser) -> None:
    app.dependency_overrides[get_current_staff] = lambda: staff


def test_roles_are_enforced_for_operations_routes(
    db: Session, staff_factory
) -> None:
    trainer = staff_factory(StaffRole.TRAINER)
    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    owner = staff_factory(StaffRole.OWNER)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_staff] = lambda: trainer
    with TestClient(app) as client:
        for path in (
            "/api/members",
            "/api/membership-plans",
            "/api/subscriptions",
            "/api/payments",
            "/api/attendance/check-ins",
        ):
            assert client.get(path).status_code == 403
        assert client.post(
            "/api/members",
            json=member_payload(phone="0712345678"),
        ).status_code == 403
        assert client.post(
            "/api/payments",
            json={
                "memberId": "00000000-0000-0000-0000-000000000001",
                "amountKes": 100,
                "method": "cash",
            },
        ).status_code == 403
        assert client.post(
            "/api/attendance/lookup",
            json={"memberId": "00000000-0000-0000-0000-000000000001"},
        ).status_code == 403
        assert client.post(
            "/api/membership-plans",
            json={
                "name": "Trainer Plan",
                "monthlyPriceKes": 1000,
                "isActive": False,
                "accessWindows": [],
            },
        ).status_code == 403

        set_staff(client, receptionist)
        assert client.get("/api/members").status_code == 200
        assert client.post(
            "/api/membership-plans",
            json={
                "name": "Reception Plan",
                "monthlyPriceKes": 1000,
                "isActive": False,
                "accessWindows": [],
            },
        ).status_code == 403

        set_staff(client, owner)
        assert client.get("/api/membership-plans?includeInactive=true").status_code == 200
    app.dependency_overrides.clear()


def test_unassigned_account_cannot_use_operations_routes(db: Session) -> None:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides.pop(get_current_staff, None)
    with TestClient(app) as client:
        response = client.get("/api/members")
    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_member_registration_duplicate_phone_and_qr_rotation(
    client: TestClient,
) -> None:
    original = create_member(client)
    assert original["phone"] == "+254712345678"
    assert original["initials"] == "SM"
    assert len(original["qrToken"]) >= 32

    duplicate = client.post(
        "/api/members",
        json=member_payload(name="Another Person", phone="+254 712 345 678"),
    )
    assert duplicate.status_code == 409

    rotated = client.post(f"/api/members/{original['id']}/qr/rotate")
    assert rotated.status_code == 200
    assert rotated.json()["qrToken"] != original["qrToken"]
    assert client.post(
        "/api/attendance/lookup",
        json={"qrToken": original["qrToken"]},
    ).status_code == 404
    assert client.post(
        "/api/attendance/lookup",
        json={"qrToken": rotated.json()["qrToken"]},
    ).status_code == 200


def test_member_profile_search_update_and_role_filter(client: TestClient) -> None:
    member = create_member(client)
    page = client.get("/api/members?search=Sam&page=1&pageSize=10")
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["id"] == member["id"]

    updated = client.patch(
        f"/api/members/{member['id']}",
        json={"fullName": "Sam Updated", "status": "inactive"},
    )
    assert updated.status_code == 200
    assert updated.json()["fullName"] == "Sam Updated"
    assert client.get("/api/members?status=inactive").json()["total"] == 1


def test_active_plan_requires_hours_and_owner_can_configure_peak_plan(
    client: TestClient, db: Session
) -> None:
    invalid = client.post(
        "/api/membership-plans",
        json={
            "name": "No Hours",
            "monthlyPriceKes": 5000,
            "isActive": True,
            "accessWindows": [],
        },
    )
    assert invalid.status_code == 422

    peak = create_plan(client, name="Peak Access", active=False, windows=[])
    assert peak["isActive"] is False
    assert not peak["scheduleConfigured"]
    assert db.get(GymSettings, 1).peak_access_hours_configured is False

    cannot_activate_without_hours = client.patch(
        f"/api/membership-plans/{peak['id']}",
        json={"isActive": True},
    )
    assert cannot_activate_without_hours.status_code == 422

    configured = client.patch(
        f"/api/membership-plans/{peak['id']}",
        json={
            "isActive": True,
            "accessWindows": [
                {"weekday": day, "startsAt": "06:00", "endsAt": "21:00"}
                for day in range(7)
            ],
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["scheduleConfigured"] is True
    assert configured.json()["isActive"] is True
    assert db.get(GymSettings, 1).peak_access_hours_configured is True


def test_subscription_calendar_month_boundaries_and_overlap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operations, "gym_now", lambda _session: fixed_now(date(2023, 1, 31), 10))
    member = create_member(client)
    plan = create_plan(client)

    first = subscribe(client, member["id"], plan["id"], "2023-01-31")
    assert first.status_code == 201, first.text
    assert first.json()["startsOn"] == "2023-01-31"
    assert first.json()["expiresOn"] == "2023-02-27"

    overlap = subscribe(client, member["id"], plan["id"], "2023-02-27")
    assert overlap.status_code == 409
    renewal = subscribe(client, member["id"], plan["id"], "2023-02-28")
    assert renewal.status_code == 201, renewal.text
    assert renewal.json()["expiresOn"] == "2023-03-27"
    assert next_calendar_month(date(2024, 1, 31)) == date(2024, 2, 29)

    history = client.get(f"/api/subscriptions?memberId={member['id']}")
    assert history.status_code == 200
    assert history.json()["total"] == 2


def test_payment_reference_is_unique_and_manual_mpesa_is_not_verified(
    client: TestClient, db: Session
) -> None:
    member = create_member(client)
    payment = client.post(
        "/api/payments",
        json={
            "memberId": member["id"],
            "amountKes": 4000,
            "method": "mpesa_manual",
            "reference": " ab123cd ",
        },
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["reference"] == "AB123CD"
    assert payment.json()["verificationStatus"] == "staff_recorded"
    assert payment.json()["status"] == "recorded"

    duplicate = client.post(
        "/api/payments",
        json={
            "memberId": member["id"],
            "amountKes": 4000,
            "method": "mpesa_manual",
            "reference": "AB123CD",
        },
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/payments?status=recorded")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    stored = db.scalar(select(Payment))
    assert stored is not None and stored.status == "recorded"


def test_void_payment_preserves_record_and_reason(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operations, "gym_now", lambda _session: fixed_now(date(2024, 1, 31), 10))
    member = create_member(client)
    payment = client.post(
        "/api/payments",
        json={"memberId": member["id"], "amountKes": 4000, "method": "cash"},
    ).json()

    voided = client.post(
        f"/api/payments/{payment['id']}/void",
        json={"reason": "Entered against wrong member"},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"
    assert voided.json()["voidReason"] == "Entered against wrong member"
    assert db.scalar(select(Payment)).status == "voided"


def test_off_peak_check_in_and_duplicate_rejection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = date(2024, 2, 14)  # Wednesday
    monkeypatch.setattr(operations, "gym_now", lambda _session: fixed_now(today, 12))
    member = create_member(client)
    plan = create_plan(client)
    sub = subscribe(client, member["id"], plan["id"], today.isoformat())
    assert sub.status_code == 201, sub.text

    review = client.post(
        "/api/attendance/lookup",
        json={"memberId": member["id"]},
    )
    assert review.status_code == 200, review.text
    assert review.json()["canCheckIn"] is True
    assert review.json()["restrictions"] == []

    check_in = client.post(
        "/api/attendance/check-ins",
        json={"memberId": member["id"], "confirmed": True, "source": "manual"},
    )
    assert check_in.status_code == 201, check_in.text
    duplicate = client.post(
        "/api/attendance/check-ins",
        json={"memberId": member["id"], "confirmed": True, "source": "manual"},
    )
    assert duplicate.status_code == 409
    duplicate_override = client.post(
        "/api/attendance/overrides",
        json={
            "memberId": member["id"],
            "confirmed": True,
            "source": "manual",
            "reason": "Please allow another entry",
        },
    )
    assert duplicate_override.status_code == 409

    history = client.get(f"/api/attendance/check-ins?date={today.isoformat()}")
    assert history.status_code == 200
    assert history.json()["total"] == 1


def test_off_peak_peak_hour_denial_expired_warning_and_override_audit(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2024, 2, 14)
    monkeypatch.setattr(operations, "gym_now", lambda _session: fixed_now(today, 16))
    member = create_member(client)
    plan = create_plan(client)
    sub = subscribe(client, member["id"], plan["id"], today.isoformat())
    assert sub.status_code == 201

    review = client.post(
        "/api/attendance/lookup",
        json={"memberId": member["id"]},
    ).json()
    assert review["canCheckIn"] is False
    assert any(item["code"] == "outside_hours" for item in review["restrictions"])
    denied = client.post(
        "/api/attendance/check-ins",
        json={"memberId": member["id"], "confirmed": True, "source": "manual"},
    )
    assert denied.status_code == 409

    no_reason = client.post(
        "/api/attendance/overrides",
        json={"memberId": member["id"], "confirmed": True, "source": "manual", "reason": "No"},
    )
    assert no_reason.status_code == 422
    approved = client.post(
        "/api/attendance/overrides",
        json={
            "memberId": member["id"],
            "confirmed": True,
            "source": "manual",
            "reason": "Owner approved late visit",
        },
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["wasOverridden"] is True
    assert approved.json()["restrictionCodes"] == ["outside_hours"]
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "attendance.check_in_overridden"))
    assert audit is not None
    assert audit.details["reason"] == "Owner approved late visit"

    db.add(
        Subscription(
            id=uuid4(),
            member_id=UUID(member["id"]),
            plan_id=UUID(plan["id"]),
            plan_name=plan["name"],
            monthly_price_kes=plan["monthlyPriceKes"],
            starts_on=date(2023, 1, 1),
            expires_on=date(2024, 1, 31),
            status="active",
        )
    )
    db.commit()
    expired_review = client.post(
        "/api/attendance/lookup",
        json={"memberId": member["id"]},
    ).json()
    # The current subscription still takes precedence; the expired record is
    # selected after the active one is marked cancelled.
    current = db.scalar(
        select(Subscription).where(Subscription.id == UUID(sub.json()["id"]))
    )
    current.status = "cancelled"
    db.commit()
    monkeypatch.setattr(operations, "gym_now", lambda _session: fixed_now(today, 16, 10))
    expired_review = client.post(
        "/api/attendance/lookup",
        json={"memberId": member["id"]},
    ).json()
    assert any(item["code"] == "expired" for item in expired_review["restrictions"])
    expired_check_in = client.post(
        "/api/attendance/check-ins",
        json={"memberId": member["id"], "confirmed": True, "source": "manual"},
    )
    assert expired_check_in.status_code == 409


def test_check_in_uses_database_row_lock_for_concurrency() -> None:
    statement = (
        select(Member)
        .where(Member.id == UUID("00000000-0000-0000-0000-000000000001"))
        .with_for_update()
    )
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
