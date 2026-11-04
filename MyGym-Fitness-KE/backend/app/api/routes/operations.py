from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner, require_owner_or_receptionist
from backend.app.db.session import get_db
from backend.app.models.attendance import CheckIn
from backend.app.models.audit_log import AuditLog
from backend.app.models.gym_settings import GymSettings
from backend.app.models.member import Member, MemberStatus
from backend.app.models.membership import (
    MembershipPlan,
    PlanAccessWindow,
    Subscription,
    SubscriptionStatus,
)
from backend.app.models.payment import Payment, PaymentMethod, PaymentStatus
from backend.app.models.staff_user import StaffUser
from backend.app.schemas.operations import (
    AccessWindowInput,
    AttendanceLookupInput,
    AttendanceReview,
    CheckInInput,
    CheckInOverrideInput,
    CheckInPage,
    CheckInResponse,
    MemberDetail,
    MemberInput,
    MemberPage,
    MemberQr,
    MemberSummary,
    MemberUpdate,
    MembershipPlanInput,
    MembershipPlanResponse,
    MembershipPlanUpdate,
    PaymentInput,
    PaymentPage,
    PaymentResponse,
    PaymentVoidInput,
    SubscriptionInput,
    SubscriptionPage,
    SubscriptionResponse,
)
from backend.app.services.access import evaluate_access
from backend.app.services.operations import (
    access_windows,
    check_in_response,
    get_gym_timezone,
    gym_now,
    local_day_bounds,
    member_detail,
    member_qr,
    member_summary,
    membership_plan_response,
    next_calendar_month,
    payment_response,
    subscription_response,
)

router = APIRouter()

_PEAK_ACCESS_PLAN_ID = UUID("c35ec58e-1762-4057-9a7d-8ab7bdbf9102")


def _raise_error(status_code: int, message: str, code: str) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={"error": message, "code": code},
    )


def _new_member_number(member_id: UUID) -> str:
    return f"MG-{member_id.hex[:12].upper()}"


def _month_period(starts_on: date) -> tuple[date, date]:
    """Return an inclusive one-calendar-month membership date range.

    The date one month after the start is the exclusive boundary; expires_on
    is the preceding day, so the member has access through the end of that day.
    """
    return starts_on, next_calendar_month(starts_on) - timedelta(days=1)


def _local_input_datetime(value: datetime, session: Session) -> datetime:
    """Treat naive staff-entered datetimes as gym-local and persist UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_gym_timezone(session))
    return value.astimezone(timezone.utc)


def _validate_member_phone_available(
    session: Session, phone: str, *, excluding: UUID | None = None
) -> None:
    stmt = select(Member.id).where(Member.phone == phone)
    if excluding is not None:
        stmt = stmt.where(Member.id != excluding)
    if session.scalar(stmt.limit(1)) is not None:
        _raise_error(409, "This phone number is already registered", "member_phone_exists")


def _member_conflict_after_integrity_error(
    session: Session, phone: str, member_id: UUID | None = None
) -> None:
    session.rollback()
    stmt = select(Member.id).where(Member.phone == phone)
    if member_id is not None:
        stmt = stmt.where(Member.id != member_id)
    if session.scalar(stmt.limit(1)) is not None:
        _raise_error(409, "This phone number is already registered", "member_phone_exists")
    raise HTTPException(
        status_code=409,
        detail={"error": "The member could not be saved", "code": "member_conflict"},
    )


def _write_plan_windows(
    session: Session,
    plan: MembershipPlan,
    windows: list[AccessWindowInput],
) -> None:
    session.execute(
        delete(PlanAccessWindow).where(PlanAccessWindow.plan_id == plan.id)
    )
    session.add_all(
        [
            PlanAccessWindow(
                plan_id=plan.id,
                weekday=window.weekday,
                starts_at=time.fromisoformat(window.starts_at),
                ends_at=time.fromisoformat(window.ends_at),
            )
            for window in windows
        ]
    )


def _sync_peak_access_setting(
    session: Session, plan: MembershipPlan, staff_id: UUID
) -> None:
    if (
        plan.id != _PEAK_ACCESS_PLAN_ID
        and plan.name.strip().casefold() != "peak access"
    ):
        return
    settings = session.get(GymSettings, 1, with_for_update=True)
    if settings is not None:
        settings.peak_access_hours_configured = bool(
            access_windows(session, plan.id)
        )
        settings.updated_by = staff_id


def _find_subscription_for_access(
    session: Session, member_id: UUID, today: date
) -> Subscription | None:
    base = select(Subscription).where(
        Subscription.member_id == member_id,
        Subscription.status != SubscriptionStatus.CANCELLED.value,
    )
    current = session.scalar(
        base.where(
            Subscription.starts_on <= today,
            Subscription.expires_on >= today,
        )
        .order_by(Subscription.starts_on.desc(), Subscription.created_at.desc())
        .limit(1)
    )
    if current is not None:
        return current

    upcoming = session.scalar(
        base.where(Subscription.starts_on > today)
        .order_by(Subscription.starts_on.asc(), Subscription.created_at.asc())
        .limit(1)
    )
    if upcoming is not None:
        return upcoming

    return session.scalar(
        base.where(Subscription.expires_on < today)
        .order_by(Subscription.expires_on.desc(), Subscription.created_at.desc())
        .limit(1)
    )


def _attendance_review(
    session: Session,
    member: Member,
    checked_at: datetime,
) -> AttendanceReview:
    local_checked_at = checked_at.astimezone(get_gym_timezone(session))
    settings = session.get(GymSettings, 1)
    if settings is None:
        _raise_error(
            503,
            "Gym settings are not initialized",
            "foundation_not_initialized",
        )

    subscription = _find_subscription_for_access(
        session, member.id, local_checked_at.date()
    )
    plan = (
        session.get(MembershipPlan, subscription.plan_id)
        if subscription is not None
        else None
    )
    windows = (
        access_windows(session, plan.id)
        if plan is not None
        else []
    )
    cutoff = checked_at.astimezone(timezone.utc) - timedelta(
        minutes=settings.attendance_duplicate_interval_minutes
    )
    duplicate_at = session.scalar(
        select(CheckIn.checked_in_at)
        .where(
            CheckIn.member_id == member.id,
            CheckIn.checked_in_at >= cutoff,
        )
        .order_by(CheckIn.checked_in_at.desc())
        .limit(1)
    )
    restrictions = evaluate_access(
        member,
        subscription,
        plan,
        windows,
        local_checked_at,
        duplicate_at,
    )

    today = local_checked_at.date()
    return AttendanceReview(
        member=member_summary(member),
        subscription=(
            subscription_response(subscription, member, today)
            if subscription is not None
            else None
        ),
        plan=membership_plan_response(session, plan) if plan is not None else None,
        checked_at=local_checked_at,
        restrictions=restrictions,
        can_check_in=not restrictions,
        duplicate_check_in_at=duplicate_at,
    )


def _lock_member(session: Session, member_id: UUID) -> Member:
    """Serialize state-changing member operations, including check-ins.

    PostgreSQL holds this row lock until commit. Check-ins re-read the duplicate
    window after acquiring it, so concurrent requests for one member cannot both
    pass the duplicate check.
    """
    member = session.scalar(
        select(Member).where(Member.id == member_id).with_for_update()
    )
    if member is None:
        _raise_error(404, "Member not found", "member_not_found")
    return member


@router.get(
    "/members",
    operation_id="listMembers",
    response_model=MemberPage,
    tags=["members"],
)
def list_members(
    search: str | None = Query(default=None, max_length=120),
    member_status: MemberStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> MemberPage:
    stmt = select(Member)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Member.full_name.ilike(pattern),
                Member.member_number.ilike(pattern),
                Member.phone.ilike(pattern),
            )
        )
    if member_status is not None:
        stmt = stmt.where(Member.status == member_status.value)

    total = session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ) or 0
    members = list(
        session.scalars(
            stmt.order_by(Member.registered_at.desc(), Member.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return MemberPage(
        items=[member_summary(member) for member in members],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/members",
    operation_id="createMember",
    response_model=MemberDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["members"],
)
def create_member(
    data: MemberInput,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> MemberDetail:
    _validate_member_phone_available(session, data.phone)
    member_id = uuid4()
    member = Member(
        id=member_id,
        member_number=_new_member_number(member_id),
        full_name=data.full_name,
        phone=data.phone,
        email=data.email,
        status=MemberStatus.ACTIVE.value,
        qr_token=secrets.token_urlsafe(32),
    )
    session.add(member)
    try:
        session.commit()
    except IntegrityError:
        _member_conflict_after_integrity_error(session, data.phone)
    session.refresh(member)
    return member_detail(member)


@router.get(
    "/members/{member_id}",
    operation_id="getMemberDetail",
    response_model=MemberDetail,
    tags=["members"],
)
def get_member_detail(
    member_id: UUID,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> MemberDetail:
    member = session.get(Member, member_id)
    if member is None:
        _raise_error(404, "Member not found", "member_not_found")
    return member_detail(member)


@router.patch(
    "/members/{member_id}",
    operation_id="updateMember",
    response_model=MemberDetail,
    tags=["members"],
)
def update_member(
    member_id: UUID,
    changes: MemberUpdate,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> MemberDetail:
    member = _lock_member(session, member_id)
    updates = changes.model_dump(exclude_unset=True)
    phone = updates.get("phone")
    if phone is not None:
        _validate_member_phone_available(session, phone, excluding=member.id)
    for field, value in updates.items():
        setattr(member, field, value.value if isinstance(value, MemberStatus) else value)
    try:
        session.commit()
    except IntegrityError:
        _member_conflict_after_integrity_error(
            session, phone or member.phone, member.id
        )
    session.refresh(member)
    return member_detail(member)


@router.post(
    "/members/{member_id}/qr/rotate",
    operation_id="rotateMemberQr",
    response_model=MemberQr,
    tags=["members"],
)
def rotate_member_qr(
    member_id: UUID,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> MemberQr:
    member = _lock_member(session, member_id)
    member.qr_token = secrets.token_urlsafe(32)
    rotated_at = gym_now(session)
    session.commit()
    session.refresh(member)
    return member_qr(member, rotated_at)


@router.get(
    "/membership-plans",
    operation_id="listMembershipPlans",
    response_model=list[MembershipPlanResponse],
    tags=["memberships"],
)
def list_membership_plans(
    include_inactive: bool = Query(default=False, alias="includeInactive"),
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> list[MembershipPlanResponse]:
    stmt = select(MembershipPlan)
    if not include_inactive or staff.role != "owner":
        stmt = stmt.where(MembershipPlan.is_active.is_(True))
    plans = list(session.scalars(stmt.order_by(MembershipPlan.name, MembershipPlan.id)))
    return [membership_plan_response(session, plan) for plan in plans]


@router.post(
    "/membership-plans",
    operation_id="createMembershipPlan",
    response_model=MembershipPlanResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["memberships"],
)
def create_membership_plan(
    data: MembershipPlanInput,
    staff: StaffUser = Depends(require_owner),
    session: Session = Depends(get_db),
) -> MembershipPlanResponse:
    plan = MembershipPlan(
        id=uuid4(),
        name=data.name,
        monthly_price_kes=data.monthly_price_kes,
        is_active=data.is_active,
        created_by_staff_id=staff.id,
        updated_by_staff_id=staff.id,
    )
    session.add(plan)
    try:
        session.flush()
        _write_plan_windows(session, plan, data.access_windows)
        session.flush()
        _sync_peak_access_setting(session, plan, staff.id)
        session.commit()
    except IntegrityError:
        session.rollback()
        _raise_error(409, "A membership plan with this name already exists", "plan_name_exists")
    session.refresh(plan)
    return membership_plan_response(session, plan)


@router.patch(
    "/membership-plans/{plan_id}",
    operation_id="updateMembershipPlan",
    response_model=MembershipPlanResponse,
    tags=["memberships"],
)
def update_membership_plan(
    plan_id: UUID,
    changes: MembershipPlanUpdate,
    staff: StaffUser = Depends(require_owner),
    session: Session = Depends(get_db),
) -> MembershipPlanResponse:
    plan = session.scalar(
        select(MembershipPlan)
        .where(MembershipPlan.id == plan_id)
        .with_for_update()
    )
    if plan is None:
        _raise_error(404, "Membership plan not found", "plan_not_found")

    updates = changes.model_dump(exclude_unset=True, exclude={"access_windows"})
    windows = (
        changes.access_windows
        if "access_windows" in changes.model_fields_set
        else None
    )
    if windows is None:
        next_windows = access_windows(session, plan.id)
    else:
        next_windows = windows
    next_active = updates.get("is_active", plan.is_active)
    if next_active and not next_windows:
        _raise_error(
            422,
            "Active plans need at least one configured access window",
            "plan_access_hours_required",
        )

    for field, value in updates.items():
        setattr(plan, field, value)
    plan.updated_by_staff_id = staff.id
    try:
        if windows is not None:
            _write_plan_windows(session, plan, windows)
            session.flush()
        _sync_peak_access_setting(session, plan, staff.id)
        session.commit()
    except IntegrityError:
        session.rollback()
        _raise_error(409, "A membership plan with this name already exists", "plan_name_exists")
    session.refresh(plan)
    return membership_plan_response(session, plan)


@router.get(
    "/subscriptions",
    operation_id="listSubscriptions",
    response_model=SubscriptionPage,
    tags=["memberships"],
)
def list_subscriptions(
    member_id: UUID | None = Query(default=None, alias="memberId"),
    subscription_state: str | None = Query(
        default=None,
        alias="status",
        pattern="^(scheduled|active|expired|cancelled)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> SubscriptionPage:
    today = gym_now(session).date()
    stmt = select(Subscription, Member).join(
        Member, Subscription.member_id == Member.id
    )
    if member_id is not None:
        stmt = stmt.where(Subscription.member_id == member_id)
    if subscription_state == "cancelled":
        stmt = stmt.where(Subscription.status == SubscriptionStatus.CANCELLED.value)
    elif subscription_state == "scheduled":
        stmt = stmt.where(
            Subscription.status != SubscriptionStatus.CANCELLED.value,
            Subscription.starts_on > today,
        )
    elif subscription_state == "expired":
        stmt = stmt.where(
            Subscription.status != SubscriptionStatus.CANCELLED.value,
            Subscription.expires_on < today,
        )
    elif subscription_state == "active":
        stmt = stmt.where(
            Subscription.status != SubscriptionStatus.CANCELLED.value,
            Subscription.starts_on <= today,
            Subscription.expires_on >= today,
        )

    total = session.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ) or 0
    rows = session.execute(
        stmt.order_by(
            Subscription.starts_on.desc(),
            Subscription.created_at.desc(),
            Subscription.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SubscriptionPage(
        items=[
            subscription_response(subscription, member, today)
            for subscription, member in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/members/{member_id}/subscriptions",
    operation_id="createSubscription",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["memberships"],
)
def create_subscription(
    member_id: UUID,
    data: SubscriptionInput,
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> SubscriptionResponse:
    member = _lock_member(session, member_id)
    plan = session.scalar(
        select(MembershipPlan)
        .where(MembershipPlan.id == data.plan_id)
        .with_for_update()
    )
    if plan is None:
        _raise_error(404, "Membership plan not found", "plan_not_found")
    if not plan.is_active or not access_windows(session, plan.id):
        _raise_error(
            422,
            "Choose an active membership plan with configured access hours",
            "plan_unavailable",
        )

    starts_on, expires_on = _month_period(data.starts_on)
    overlap = session.scalar(
        select(Subscription.id)
        .where(
            Subscription.member_id == member.id,
            Subscription.status != SubscriptionStatus.CANCELLED.value,
            Subscription.starts_on <= expires_on,
            Subscription.expires_on >= starts_on,
        )
        .limit(1)
    )
    if overlap is not None:
        _raise_error(
            409,
            "This subscription overlaps an existing membership period",
            "subscription_period_overlap",
        )

    today = gym_now(session).date()
    subscription = Subscription(
        id=uuid4(),
        member_id=member.id,
        plan_id=plan.id,
        plan_name=plan.name,
        monthly_price_kes=plan.monthly_price_kes,
        starts_on=starts_on,
        expires_on=expires_on,
        status=(
            SubscriptionStatus.SCHEDULED.value
            if starts_on > today
            else SubscriptionStatus.ACTIVE.value
        ),
        created_by_staff_id=staff.id,
    )
    session.add(subscription)
    session.commit()
    session.refresh(subscription)
    return subscription_response(subscription, member, today)


@router.get(
    "/payments",
    operation_id="listPayments",
    response_model=PaymentPage,
    tags=["payments"],
)
def list_payments(
    member_id: UUID | None = Query(default=None, alias="memberId"),
    payment_state: PaymentStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> PaymentPage:
    stmt = (
        select(Payment, Member, StaffUser)
        .join(Member, Payment.member_id == Member.id)
        .outerjoin(StaffUser, Payment.recorded_by_staff_id == StaffUser.id)
    )
    if member_id is not None:
        stmt = stmt.where(Payment.member_id == member_id)
    if payment_state is not None:
        stmt = stmt.where(Payment.status == payment_state.value)
    total = session.scalar(
        select(func.count()).select_from(
            select(Payment.id)
            .join(Member, Payment.member_id == Member.id)
            .where(
                *(
                    [Payment.member_id == member_id]
                    if member_id is not None
                    else []
                ),
                *(
                    [Payment.status == payment_state.value]
                    if payment_state is not None
                    else []
                ),
            )
            .subquery()
        )
    ) or 0
    rows = session.execute(
        stmt.order_by(Payment.paid_at.desc(), Payment.created_at.desc(), Payment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PaymentPage(
        items=[
            payment_response(payment, member, recorded_by)
            for payment, member, recorded_by in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/payments",
    operation_id="recordPayment",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["payments"],
)
def record_payment(
    data: PaymentInput,
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> PaymentResponse:
    member = session.get(Member, data.member_id)
    if member is None:
        _raise_error(404, "Member not found", "member_not_found")
    if data.subscription_id is not None:
        subscription = session.get(Subscription, data.subscription_id)
        if subscription is None or subscription.member_id != member.id:
            _raise_error(404, "Subscription not found for this member", "subscription_not_found")
    if data.reference is not None and session.scalar(
        select(Payment.id).where(Payment.reference == data.reference).limit(1)
    ) is not None:
        _raise_error(
            409,
            "This payment reference has already been recorded",
            "payment_reference_exists",
        )

    payment = Payment(
        id=uuid4(),
        member_id=member.id,
        subscription_id=data.subscription_id,
        amount_kes=data.amount_kes,
        method=data.method.value,
        reference=data.reference,
        status=PaymentStatus.RECORDED.value,
        paid_at=_local_input_datetime(data.paid_at, session)
        if data.paid_at is not None
        else gym_now(session).astimezone(timezone.utc),
        recorded_by_staff_id=staff.id,
    )
    session.add(payment)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if data.reference is not None and session.scalar(
            select(Payment.id).where(Payment.reference == data.reference).limit(1)
        ) is not None:
            _raise_error(
                409,
                "This payment reference has already been recorded",
                "payment_reference_exists",
            )
        raise
    session.refresh(payment)
    return payment_response(payment, member, staff)


@router.post(
    "/payments/{payment_id}/void",
    operation_id="voidPayment",
    response_model=PaymentResponse,
    tags=["payments"],
)
def void_payment(
    payment_id: UUID,
    data: PaymentVoidInput,
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> PaymentResponse:
    payment = session.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if payment is None:
        _raise_error(404, "Payment not found", "payment_not_found")
    if payment.status == PaymentStatus.VOIDED.value:
        _raise_error(409, "This payment has already been voided", "payment_already_voided")
    member = session.get(Member, payment.member_id)
    payment.status = PaymentStatus.VOIDED.value
    payment.voided_by_staff_id = staff.id
    payment.voided_at = gym_now(session).astimezone(timezone.utc)
    payment.void_reason = data.reason
    session.commit()
    session.refresh(payment)
    return payment_response(payment, member, staff)


@router.post(
    "/attendance/lookup",
    operation_id="lookupAttendance",
    response_model=AttendanceReview,
    tags=["attendance"],
)
def lookup_attendance(
    data: AttendanceLookupInput,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> AttendanceReview:
    if data.member_id is not None:
        member = session.get(Member, data.member_id)
    else:
        member = session.scalar(
            select(Member).where(Member.qr_token == data.qr_token)
        )
    if member is None:
        _raise_error(404, "Member or QR token not found", "member_not_found")
    return _attendance_review(session, member, gym_now(session))


@router.get(
    "/attendance/check-ins",
    operation_id="listCheckIns",
    response_model=CheckInPage,
    tags=["attendance"],
)
def list_check_ins(
    day: date | None = Query(default=None, alias="date"),
    member_id: UUID | None = Query(default=None, alias="memberId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> CheckInPage:
    zone = get_gym_timezone(session)
    local_day = day or gym_now(session).date()
    start_at, end_at = local_day_bounds(local_day, zone)
    stmt = (
        select(CheckIn, Member, StaffUser)
        .join(Member, CheckIn.member_id == Member.id)
        .outerjoin(StaffUser, CheckIn.staff_id == StaffUser.id)
        .where(
            CheckIn.checked_in_at >= start_at,
            CheckIn.checked_in_at < end_at,
        )
    )
    if member_id is not None:
        stmt = stmt.where(CheckIn.member_id == member_id)
    total = session.scalar(
        select(func.count()).select_from(
            select(CheckIn.id)
            .where(
                CheckIn.checked_in_at >= start_at,
                CheckIn.checked_in_at < end_at,
                *(
                    [CheckIn.member_id == member_id]
                    if member_id is not None
                    else []
                ),
            )
            .subquery()
        )
    ) or 0
    rows = session.execute(
        stmt.order_by(CheckIn.checked_in_at.desc(), CheckIn.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CheckInPage(
        items=[
            check_in_response(check_in, member, staff)
            for check_in, member, staff in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def _create_check_in(
    session: Session,
    staff: StaffUser,
    member: Member,
    data: CheckInInput | CheckInOverrideInput,
    review: AttendanceReview,
    *,
    overridden: bool,
    reason: str | None = None,
) -> CheckIn:
    check_in = CheckIn(
        id=uuid4(),
        member_id=member.id,
        staff_id=staff.id,
        checked_in_at=review.checked_at.astimezone(timezone.utc),
        source=data.source,
        was_overridden=overridden,
        override_reason=reason,
        restriction_codes=[item.code for item in review.restrictions],
    )
    session.add(check_in)
    if overridden:
        session.add(
            AuditLog(
                actor_staff_id=staff.id,
                action="attendance.check_in_overridden",
                entity_type="check_in",
                entity_id=str(check_in.id),
                details={
                    "member_id": str(member.id),
                    "source": data.source,
                    "reason": reason,
                    "restriction_codes": [
                        item.code for item in review.restrictions
                    ],
                },
            )
        )
    session.commit()
    session.refresh(check_in)
    return check_in


@router.post(
    "/attendance/check-ins",
    operation_id="confirmCheckIn",
    response_model=CheckInResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["attendance"],
)
def confirm_check_in(
    data: CheckInInput,
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> CheckInResponse:
    member = _lock_member(session, data.member_id)
    review = _attendance_review(session, member, gym_now(session))
    if review.restrictions:
        _raise_error(
            409,
            "Access is restricted or a recent check-in already exists",
            "check_in_restricted",
        )
    check_in = _create_check_in(
        session, staff, member, data, review, overridden=False
    )
    return check_in_response(check_in, member, staff)


@router.post(
    "/attendance/overrides",
    operation_id="overrideCheckIn",
    response_model=CheckInResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["attendance"],
)
def override_check_in(
    data: CheckInOverrideInput,
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> CheckInResponse:
    member = _lock_member(session, data.member_id)
    review = _attendance_review(session, member, gym_now(session))
    if not review.restrictions or any(
        item.code == "duplicate" or not item.override_allowed
        for item in review.restrictions
    ):
        _raise_error(
            409,
            "Only an allowed access restriction can be overridden",
            "check_in_override_not_allowed",
        )
    check_in = _create_check_in(
        session,
        staff,
        member,
        data,
        review,
        overridden=True,
        reason=data.reason,
    )
    return check_in_response(check_in, member, staff)
