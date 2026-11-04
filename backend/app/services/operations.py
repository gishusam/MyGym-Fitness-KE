from __future__ import annotations

import calendar
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.gym_settings import GymSettings
from backend.app.models.member import Member
from backend.app.models.membership import MembershipPlan, PlanAccessWindow, Subscription
from backend.app.models.payment import Payment
from backend.app.models.staff_user import StaffUser
from backend.app.schemas.operations import (
    AccessWindow,
    CheckInResponse,
    MemberDetail,
    MemberQr,
    MemberSummary,
    MembershipPlanResponse,
    PaymentResponse,
    SubscriptionResponse,
)
from backend.app.models.attendance import CheckIn


def initials(full_name: str) -> str:
    return "".join(part[0].upper() for part in full_name.split()[:2]) or "MG"


def member_summary(member: Member) -> MemberSummary:
    return MemberSummary(
        id=member.id,
        member_number=member.member_number,
        full_name=member.full_name,
        phone=member.phone,
        email=member.email,
        status=member.status,
        registered_at=member.registered_at,
        initials=initials(member.full_name),
    )


def member_detail(member: Member) -> MemberDetail:
    return MemberDetail(
        **member_summary(member).model_dump(),
        qr_token=member.qr_token,
    )


def member_qr(member: Member, rotated_at: datetime) -> MemberQr:
    return MemberQr(
        member_id=member.id,
        member_number=member.member_number,
        qr_token=member.qr_token,
        rotated_at=rotated_at,
    )


def get_gym_timezone(session: Session) -> ZoneInfo:
    settings = session.get(GymSettings, 1)
    if settings is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Gym settings are not initialized",
                "code": "foundation_not_initialized",
            },
        )
    try:
        return ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=503,
            detail={"error": "Gym timezone is invalid", "code": "invalid_gym_timezone"},
        ) from error


def gym_now(session: Session) -> datetime:
    return datetime.now(get_gym_timezone(session))


def local_day_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(date.fromordinal(day.toordinal() + 1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def next_calendar_month(day: date) -> date:
    month_index = day.month % 12 + 1
    year = day.year + (1 if day.month == 12 else 0)
    last_day = calendar.monthrange(year, month_index)[1]
    return date(year, month_index, min(day.day, last_day))


def access_windows(session: Session, plan_id) -> list[PlanAccessWindow]:
    return list(
        session.scalars(
            select(PlanAccessWindow)
            .where(PlanAccessWindow.plan_id == plan_id)
            .order_by(PlanAccessWindow.weekday)
        )
    )


def membership_plan_response(
    session: Session, plan: MembershipPlan
) -> MembershipPlanResponse:
    windows = access_windows(session, plan.id)
    return MembershipPlanResponse(
        id=plan.id,
        name=plan.name,
        monthly_price_kes=plan.monthly_price_kes,
        is_active=plan.is_active,
        schedule_configured=bool(windows),
        access_windows=[
            AccessWindow(
                id=window.id,
                weekday=window.weekday,
                starts_at=window.starts_at.strftime("%H:%M"),
                ends_at=window.ends_at.strftime("%H:%M"),
            )
            for window in windows
        ],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def subscription_status(subscription: Subscription, today: date) -> str:
    if subscription.status == "cancelled":
        return "cancelled"
    if subscription.starts_on > today:
        return "scheduled"
    if subscription.expires_on < today:
        return "expired"
    return "active"


def subscription_response(
    subscription: Subscription, member: Member, today: date
) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=subscription.id,
        member_id=member.id,
        member_name=member.full_name,
        member_number=member.member_number,
        plan_id=subscription.plan_id,
        plan_name=subscription.plan_name,
        monthly_price_kes=subscription.monthly_price_kes,
        starts_on=subscription.starts_on,
        expires_on=subscription.expires_on,
        status=subscription_status(subscription, today),
        created_at=subscription.created_at,
    )


def payment_response(
    payment: Payment, member: Member, recorded_by: StaffUser | None
) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        member_id=member.id,
        member_name=member.full_name,
        member_number=member.member_number,
        subscription_id=payment.subscription_id,
        amount_kes=payment.amount_kes,
        method=payment.method,
        reference=payment.reference,
        status=payment.status,
        paid_at=payment.paid_at,
        recorded_by_name=recorded_by.name if recorded_by else "Former staff",
        created_at=payment.created_at,
        void_reason=payment.void_reason,
    )


def check_in_response(
    check_in: CheckIn, member: Member, staff: StaffUser | None
) -> CheckInResponse:
    return CheckInResponse(
        id=check_in.id,
        member_id=member.id,
        member_name=member.full_name,
        member_number=member.member_number,
        checked_in_at=check_in.checked_in_at,
        source=check_in.source,
        was_overridden=check_in.was_overridden,
        override_reason=check_in.override_reason,
        restriction_codes=check_in.restriction_codes or [],
        staff_name=staff.name if staff else "Former staff",
    )
