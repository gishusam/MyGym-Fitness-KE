from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import (
    require_fitness_staff,
    require_owner,
    require_owner_or_receptionist,
)
from backend.app.db.session import get_db
from backend.app.models.attendance import CheckIn
from backend.app.models.audit_log import AuditLog
from backend.app.models.fitness_assessment import FitnessAssessment
from backend.app.models.gym_settings import GymSettings
from backend.app.models.member import Member, MemberStatus
from backend.app.models.membership_upgrade import MembershipUpgrade
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
    FitnessAssessmentResponse,
    FitnessAssessmentHistory,
    FitnessAssessmentHistoryItem,
    FitnessAssessmentRecordInput,
    FitnessAssessmentSaved,
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
    MembershipUpgradeInput,
    MembershipUpgradeResponse,
    SubscriptionPage,
    SubscriptionResponse,
)
from backend.app.services.onboarding import issue_member_onboarding_token
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


def _member_detail_with_fitness(session: Session, member: Member) -> MemberDetail:
    latest = session.scalar(
        select(FitnessAssessment)
        .where(FitnessAssessment.member_id == member.id)
        .order_by(FitnessAssessment.recorded_at.desc(), FitnessAssessment.id.desc())
        .limit(1)
    )
    detail = member_detail(member)
    if latest is not None:
        detail.latest_assessment = FitnessAssessmentResponse(
            id=latest.id,
            recorded_at=latest.recorded_at,
            weight_kg=latest.weight_kg,
            height_cm=latest.height_cm,
            bmi=latest.bmi,
            body_fat_percent=latest.body_fat_percent,
            muscle_percent=latest.muscle_percent,
            visceral_fat_level=latest.visceral_fat_level,
        )
    return detail


# MYGYM_TASK5_ASSESSMENTS_V1 — historical, staff-authenticated fitness tracking.
def _assessment_item(item: FitnessAssessment) -> FitnessAssessmentHistoryItem:
    return FitnessAssessmentHistoryItem(
        id=item.id, recorded_at=item.recorded_at, weight_kg=item.weight_kg,
        height_cm=item.height_cm, bmi=item.bmi,
        body_fat_percent=item.body_fat_percent, muscle_percent=item.muscle_percent,
        visceral_fat_level=item.visceral_fat_level,
    )


@router.get(
    "/members/{member_id}/fitness-assessments",
    response_model=FitnessAssessmentHistory,
    tags=["fitness"],
)
def list_member_fitness_assessments(
    member_id: UUID,
    _staff: StaffUser = Depends(require_fitness_staff),
    session: Session = Depends(get_db),
) -> FitnessAssessmentHistory:
    if session.get(Member, member_id) is None:
        _raise_error(404, "Member not found", "member_not_found")
    results = list(session.scalars(
        select(FitnessAssessment)
        .where(FitnessAssessment.member_id == member_id)
        .order_by(FitnessAssessment.recorded_at.desc(), FitnessAssessment.id.desc())
        .limit(100)
    ))
    return FitnessAssessmentHistory(items=[_assessment_item(item) for item in results])


@router.post(
    "/members/{member_id}/fitness-assessments",
    response_model=FitnessAssessmentSaved,
    status_code=status.HTTP_201_CREATED,
    tags=["fitness"],
)
def record_member_fitness_assessment(
    member_id: UUID,
    data: FitnessAssessmentRecordInput,
    staff: StaffUser = Depends(require_fitness_staff),
    session: Session = Depends(get_db),
) -> FitnessAssessmentSaved:
    member = _lock_member(session, member_id)
    height_m = data.height_cm / 100 if data.height_cm is not None else None
    bmi = (
        round(data.weight_kg / (height_m ** 2), 1)
        if data.weight_kg is not None and height_m else None
    )
    item = FitnessAssessment(
        id=uuid4(), member_id=member.id, recorded_by_staff_id=staff.id,
        recorded_at=datetime.now(timezone.utc),
        weight_kg=data.weight_kg, height_cm=data.height_cm, bmi=bmi,
        body_fat_percent=data.body_fat_percent, muscle_percent=data.muscle_percent,
        visceral_fat_level=data.visceral_fat_level,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return FitnessAssessmentSaved(**_assessment_item(item).model_dump())


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
    # Persist the parent row before its FK-dependent assessment; commit remains atomic.
    # Flush within the guarded transaction so any DB failure is handled consistently.
    try:
        session.flush()
    except IntegrityError:
        _member_conflict_after_integrity_error(session, data.phone)
    onboarding_token, _expires_at = issue_member_onboarding_token(session, member)
    if data.initial_assessment is not None:
        metrics = data.initial_assessment
        height_m = metrics.height_cm / 100 if metrics.height_cm else None
        bmi = round(metrics.weight_kg / (height_m * height_m), 1) if metrics.weight_kg is not None and height_m else None
        session.add(FitnessAssessment(
            id=uuid4(), member_id=member.id, recorded_by_staff_id=_staff.id,
            weight_kg=metrics.weight_kg, height_cm=metrics.height_cm, bmi=bmi,
            body_fat_percent=metrics.body_fat_percent, muscle_percent=metrics.muscle_percent,
            visceral_fat_level=metrics.visceral_fat_level,
        ))
    try:
        session.commit()
    except IntegrityError as exc:
        # Log metadata only; never log SQL parameters containing member information.
        diag = getattr(exc.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        table = getattr(diag, "table_name", None)
        sqlstate = getattr(exc.orig, "sqlstate", None)
        print(f"[MYGYM MEMBER SAVE] constraint={constraint!r}, table={table!r}, sqlstate={sqlstate!r}", flush=True)
        _member_conflict_after_integrity_error(session, data.phone)
    session.refresh(member)
    detail = _member_detail_with_fitness(session, member)
    detail.onboarding_token = onboarding_token
    return detail


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
    return _member_detail_with_fitness(session, member)


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
    return _member_detail_with_fitness(session, member)


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


# MYGYM_UPGRADE_V1 — atomic effective plan change + top-up + immutable upgrade history.
@router.post(
    "/members/{member_id}/subscriptions/{subscription_id}/upgrade",
    response_model=MembershipUpgradeResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["memberships"],
)
def upgrade_membership(
    member_id: UUID,
    subscription_id: UUID,
    data: MembershipUpgradeInput,
    staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> MembershipUpgradeResponse:
    # The member row lock serializes all upgrades for this member.
    member = _lock_member(session, member_id)
    current = session.scalar(
        select(Subscription)
        .where(Subscription.id == subscription_id, Subscription.member_id == member.id)
        .with_for_update()
    )
    if current is None:
        _raise_error(404, "Membership not found", "subscription_not_found")
    today = gym_now(session).date()
    if current.status == SubscriptionStatus.CANCELLED.value or not (current.starts_on <= today <= current.expires_on):
        _raise_error(422, "Only an ongoing membership can be upgraded", "upgrade_requires_active_term")
    if session.scalar(select(MembershipUpgrade.id).where(MembershipUpgrade.subscription_id == current.id).limit(1)):
        _raise_error(409, "This membership has already been upgraded", "already_upgraded")
    target = session.scalar(
        select(MembershipPlan).where(MembershipPlan.id == data.to_plan_id).with_for_update()
    )
    if target is None:
        _raise_error(404, "Target membership plan not found", "plan_not_found")
    if not target.is_active or not access_windows(session, target.id):
        _raise_error(422, "Configure and activate the new plan's access hours first", "plan_unavailable")
    difference = target.monthly_price_kes - current.monthly_price_kes
    if difference <= 0:
        _raise_error(422, "Choose a higher-priced plan for an upgrade", "upgrade_requires_higher_plan")
    if session.scalar(select(Payment.id).where(Payment.reference == data.reference).limit(1)):
        _raise_error(409, "This payment reference has already been recorded", "payment_reference_exists")

    # Payment reference is staff-entered evidence only; it is NOT Safaricom verified.
    payment = Payment(
        id=uuid4(), member_id=member.id, subscription_id=current.id,
        amount_kes=difference, method=data.method.value, reference=data.reference,
        status=PaymentStatus.RECORDED.value,
        paid_at=gym_now(session).astimezone(timezone.utc), recorded_by_staff_id=staff.id,
    )
    session.add(payment)
    session.flush()  # Resolve payment FK deterministically before upgrade record.
    upgrade = MembershipUpgrade(
        id=uuid4(), subscription_id=current.id, member_id=member.id,
        from_plan_id=current.plan_id, from_plan_name=current.plan_name,
        from_price_kes=current.monthly_price_kes,
        to_plan_id=target.id, to_plan_name=target.name,
        to_price_kes=target.monthly_price_kes, topup_kes=difference,
        payment_id=payment.id, staff_id=staff.id,
    )
    session.add(upgrade)
    # The effective plan changes, but dates and the original payments never change.
    current.plan_id = target.id
    current.plan_name = target.name
    current.monthly_price_kes = target.monthly_price_kes
    session.add(AuditLog(
        id=uuid4(), actor_staff_id=staff.id, action="membership_upgraded",
        entity_type="subscription", entity_id=str(current.id),
        details={
            "member_id": str(member.id), "from_plan_id": str(upgrade.from_plan_id),
            "to_plan_id": str(target.id), "topup_kes": difference,
            "payment_id": str(payment.id), "payment_reference": data.reference,
            "expires_on": current.expires_on.isoformat(),
        },
    ))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if session.scalar(select(Payment.id).where(Payment.reference == data.reference).limit(1)):
            _raise_error(409, "This payment reference has already been recorded", "payment_reference_exists")
        _raise_error(409, "Membership was changed concurrently; refresh and try again", "upgrade_conflict")
    return MembershipUpgradeResponse(
        id=upgrade.id, subscription_id=current.id,
        from_plan_name=upgrade.from_plan_name, to_plan_name=upgrade.to_plan_name,
        topup_kes=difference, payment_id=payment.id, expires_on=current.expires_on,
    )


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
    if session.scalar(select(MembershipUpgrade.id).where(MembershipUpgrade.payment_id == payment.id).limit(1)):
        _raise_error(409, "Upgrade top-ups cannot be voided independently", "upgrade_payment_void_prohibited")
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
