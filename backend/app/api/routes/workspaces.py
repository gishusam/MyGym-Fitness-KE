from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.auth import get_current_staff, require_owner_or_trainer
from backend.app.db.session import get_db
from backend.app.models.attendance import CheckIn
from backend.app.models.fitness_assessment import FitnessAssessment
from backend.app.models.gym_event import EventRegistration, GymEvent
from backend.app.models.gym_settings import GymSettings
from backend.app.models.member import Member, MemberStatus
from backend.app.models.membership import Subscription, SubscriptionStatus
from backend.app.models.payment import Payment, PaymentStatus
from backend.app.models.staff_user import StaffStatus, StaffUser
from backend.app.models.workout import WorkoutAssignment
from backend.app.schemas.workspaces import (
    AttendanceDay,
    DashboardSummary,
    EventMember,
    EventResponse,
    ExpiringMembership,
    TrainerMember,
)
from backend.app.services.operations import get_gym_timezone, gym_now, local_day_bounds

router = APIRouter(tags=["workspaces"])


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _event_response(session: Session, event: GymEvent, instructor_name: str | None) -> EventResponse:
    registered = session.scalar(
        select(func.count())
        .select_from(EventRegistration)
        .where(
            EventRegistration.event_id == event.id,
            EventRegistration.status == "confirmed",
        )
    ) or 0
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        starts_at=_aware_utc(event.starts_at),
        ends_at=_aware_utc(event.ends_at),
        capacity=event.capacity,
        instructor_staff_id=event.instructor_staff_id,
        instructor_name=instructor_name,
        status=event.status,
        registered_count=registered,
        remaining_slots=max(event.capacity - registered, 0),
        cover_url=f"/api/events/{event.id}/cover" if event.cover_storage_key else None,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _expiring_memberships(
    session: Session, today: date, days_ahead: int
) -> list[ExpiringMembership]:
    rows = session.execute(
        select(Subscription, Member)
        .join(Member, Subscription.member_id == Member.id)
        .where(
            Subscription.status != SubscriptionStatus.CANCELLED.value,
            Subscription.starts_on <= today,
            Subscription.expires_on >= today,
            Subscription.expires_on <= today + timedelta(days=days_ahead),
            Member.status == MemberStatus.ACTIVE.value,
        )
        .order_by(Subscription.expires_on, Member.full_name)
        .limit(8)
    ).all()
    return [
        ExpiringMembership(
            member_id=member.id,
            member_number=member.member_number,
            full_name=member.full_name,
            expires_on=subscription.expires_on,
            days_remaining=max((subscription.expires_on - today).days, 0),
        )
        for subscription, member in rows
    ]


def _attendance_trend(session: Session, today: date) -> list[AttendanceDay]:
    zone = get_gym_timezone(session)
    first_day = today - timedelta(days=6)
    start_utc, _ = local_day_bounds(first_day, zone)
    _, end_utc = local_day_bounds(today, zone)
    rows = session.scalars(
        select(CheckIn.checked_in_at).where(
            CheckIn.checked_in_at >= start_utc,
            CheckIn.checked_in_at < end_utc,
        )
    )
    counts = {first_day + timedelta(days=index): 0 for index in range(7)}
    for timestamp in rows:
        counts[_aware_utc(timestamp).astimezone(zone).date()] += 1
    return [AttendanceDay(day=day, check_ins=count) for day, count in counts.items()]


@router.get(
    "/dashboard/summary",
    operation_id="getDashboardSummary",
    response_model=DashboardSummary,
)
def dashboard_summary(
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> DashboardSummary:
    now = gym_now(session)
    today = now.date()
    settings = session.get(GymSettings, 1)
    renewal_days = settings.renewal_reminder_days_before if settings else 7
    today_start, tomorrow_start = local_day_bounds(today, now.tzinfo)
    check_ins_today = session.scalar(
        select(func.count())
        .select_from(CheckIn)
        .where(
            CheckIn.checked_in_at >= today_start,
            CheckIn.checked_in_at < tomorrow_start,
        )
    ) or 0
    expiring = _expiring_memberships(session, today, renewal_days)

    if staff.role == "owner":
        active_members = session.scalar(
            select(func.count(func.distinct(Subscription.member_id)))
            .join(Member, Subscription.member_id == Member.id)
            .where(
                Subscription.status != SubscriptionStatus.CANCELLED.value,
                Subscription.starts_on <= today,
                Subscription.expires_on >= today,
                Member.status == MemberStatus.ACTIVE.value,
            )
        ) or 0
        month_start = datetime.combine(today.replace(day=1), time.min, tzinfo=now.tzinfo)
        payment_count = session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.status == PaymentStatus.RECORDED.value,
                Payment.paid_at >= month_start.astimezone(timezone.utc),
                Payment.paid_at < _aware_utc(now),
            )
        ) or 0
        revenue = session.scalar(
            select(func.sum(Payment.amount_kes)).where(
                Payment.status == PaymentStatus.RECORDED.value,
                Payment.paid_at >= month_start.astimezone(timezone.utc),
                Payment.paid_at < _aware_utc(now),
            )
        )
        start_30_days = (now - timedelta(days=30)).astimezone(timezone.utc)
        new_members = session.scalar(
            select(func.count())
            .select_from(Member)
            .where(Member.registered_at >= start_30_days, Member.registered_at <= _aware_utc(now))
        ) or 0
        staff_count = session.scalar(
            select(func.count())
            .select_from(StaffUser)
            .where(StaffUser.status == StaffStatus.ACTIVE.value)
        ) or 0
        return DashboardSummary(
            role=staff.role,
            active_members=active_members,
            new_members_last_30_days=new_members,
            revenue_this_month_kes=int(revenue) if payment_count else None,
            payments_this_month=payment_count,
            memberships_expiring=expiring,
            check_ins_today=check_ins_today,
            attendance_trend=_attendance_trend(session, today),
            staff_count=staff_count,
        )

    if staff.role == "receptionist":
        inactive_count = session.scalar(
            select(func.count())
            .select_from(Member)
            .where(Member.status == MemberStatus.INACTIVE.value)
        ) or 0
        return DashboardSummary(
            role=staff.role,
            memberships_expiring=expiring,
            inactive_members=inactive_count,
            check_ins_today=check_ins_today,
        )

    active_members = session.scalar(
        select(func.count())
        .select_from(Member)
        .where(Member.status == MemberStatus.ACTIVE.value)
    ) or 0
    recent_assessments = session.scalar(
        select(func.count())
        .select_from(FitnessAssessment)
        .where(
            FitnessAssessment.recorded_at >= (_aware_utc(now) - timedelta(days=30)),
            FitnessAssessment.recorded_at <= _aware_utc(now),
        )
    ) or 0
    assigned_workouts = session.scalar(
        select(func.count())
        .select_from(WorkoutAssignment)
        .where(WorkoutAssignment.status.in_(("assigned", "in_progress")))
    ) or 0
    upcoming = session.execute(
        select(GymEvent, StaffUser.name)
        .outerjoin(StaffUser, GymEvent.instructor_staff_id == StaffUser.id)
        .where(
            GymEvent.status == "published",
            GymEvent.starts_at >= _aware_utc(now),
        )
        .order_by(GymEvent.starts_at)
        .limit(4)
    ).all()
    return DashboardSummary(
        role=staff.role,
        trainer_member_count=active_members,
        recent_assessments=recent_assessments,
        assigned_workouts=assigned_workouts,
        upcoming_events=[
            _event_response(session, event, instructor_name)
            for event, instructor_name in upcoming
        ],
    )


@router.get(
    "/trainer/members",
    operation_id="listTrainerMembers",
    response_model=list[TrainerMember],
)
def list_trainer_members(
    search: str | None = Query(default=None, max_length=120),
    _staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> list[TrainerMember]:
    latest = (
        select(
            FitnessAssessment.id.label("id"),
            FitnessAssessment.member_id.label("member_id"),
            FitnessAssessment.recorded_at.label("recorded_at"),
            FitnessAssessment.weight_kg.label("weight_kg"),
            FitnessAssessment.height_cm.label("height_cm"),
            FitnessAssessment.bmi.label("bmi"),
            FitnessAssessment.body_fat_percent.label("body_fat_percent"),
            FitnessAssessment.muscle_percent.label("muscle_percent"),
            FitnessAssessment.visceral_fat_level.label("visceral_fat_level"),
            func.row_number()
            .over(
                partition_by=FitnessAssessment.member_id,
                order_by=(FitnessAssessment.recorded_at.desc(), FitnessAssessment.id.desc()),
            )
            .label("row_number"),
        )
        .subquery()
    )
    counts = (
        select(
            FitnessAssessment.member_id.label("member_id"),
            func.count(FitnessAssessment.id).label("assessment_count"),
        )
        .group_by(FitnessAssessment.member_id)
        .subquery()
    )
    stmt = (
        select(
            Member,
            latest.c.id,
            latest.c.recorded_at,
            latest.c.weight_kg,
            latest.c.height_cm,
            latest.c.bmi,
            latest.c.body_fat_percent,
            latest.c.muscle_percent,
            latest.c.visceral_fat_level,
            counts.c.assessment_count,
        )
        .outerjoin(latest, and_(latest.c.member_id == Member.id, latest.c.row_number == 1))
        .outerjoin(counts, counts.c.member_id == Member.id)
        .where(Member.status == MemberStatus.ACTIVE.value)
    )
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Member.full_name.ilike(pattern),
                Member.member_number.ilike(pattern),
            )
        )
    rows = session.execute(stmt.order_by(Member.full_name, Member.id).limit(200)).all()
    return [
        TrainerMember(
            id=member.id,
            member_number=member.member_number,
            full_name=member.full_name,
            status=member.status,
            assessment_count=assessment_count or 0,
            latest_assessment=(
                {
                    "id": assessment_id,
                    "recorded_at": recorded_at,
                    "weight_kg": weight_kg,
                    "height_cm": height_cm,
                    "bmi": bmi,
                    "body_fat_percent": body_fat_percent,
                    "muscle_percent": muscle_percent,
                    "visceral_fat_level": visceral_fat_level,
                }
                if assessment_id
                else None
            ),
        )
        for (
            member,
            assessment_id,
            recorded_at,
            weight_kg,
            height_cm,
            bmi,
            body_fat_percent,
            muscle_percent,
            visceral_fat_level,
            assessment_count,
        ) in rows
    ]


@router.get(
    "/events/members",
    operation_id="searchEventMembers",
    response_model=list[EventMember],
)
def search_event_members(
    search: str = Query(min_length=1, max_length=120),
    _staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> list[Member]:
    pattern = f"%{search.strip()}%"
    return list(
        session.scalars(
            select(Member)
            .where(
                or_(
                    Member.full_name.ilike(pattern),
                    Member.member_number.ilike(pattern),
                    Member.phone.ilike(pattern),
                ),
                Member.status == MemberStatus.ACTIVE.value,
            )
            .order_by(Member.full_name, Member.id)
            .limit(10)
        )
    )
