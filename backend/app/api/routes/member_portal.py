from __future__ import annotations

from datetime import date, datetime, time, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.app.api.routes.events import (
    _event_response,
    _registration_response,
    _stored_utc,
    register_event_member,
)
from backend.app.core.auth import get_current_member, get_member_db
from backend.app.models.attendance import CheckIn
from backend.app.models.fitness_assessment import FitnessAssessment
from backend.app.models.gym_event import EventRegistration, GymEvent
from backend.app.models.member import Member
from backend.app.models.membership import Subscription
from backend.app.models.staff_user import StaffUser
from backend.app.models.workout import (
    WorkoutAssignment,
    WorkoutExercise,
    WorkoutProgram,
    WorkoutSession,
)
from backend.app.schemas.member_portal import (
    MemberEventResponse,
    MemberMembership,
    MemberProfileResponse,
    MemberProgressResponse,
    MemberWorkoutExercise,
    MemberWorkoutResponse,
    MemberWorkoutSessionInput,
    MemberWorkoutSessionResponse,
)
from backend.app.schemas.operations import FitnessAssessmentHistoryItem
from backend.app.schemas.workspaces import EventRegistrationResponse
from backend.app.services.operations import (
    gym_now,
    local_day_bounds,
    next_calendar_month,
    subscription_status,
)

router = APIRouter(prefix="/member", tags=["member app"])


def _month_bounds(session: Session, today: date) -> tuple[datetime, datetime]:
    zone = gym_now(session).tzinfo
    start, _ = local_day_bounds(date(today.year, today.month, 1), zone)
    end, _ = local_day_bounds(next_calendar_month(date(today.year, today.month, 1)), zone)
    return start, end


def _check_ins_this_month(session: Session, member: Member, today: date) -> int:
    start, end = _month_bounds(session, today)
    return int(
        session.scalar(
            select(func.count(CheckIn.id)).where(
                CheckIn.member_id == member.id,
                CheckIn.checked_in_at >= start,
                CheckIn.checked_in_at < end,
            )
        )
        or 0
    )


def _latest_membership(
    session: Session, member: Member, today: date
) -> MemberMembership | None:
    subscriptions = list(
        session.scalars(
            select(Subscription)
            .where(Subscription.member_id == member.id)
            .order_by(Subscription.starts_on.desc(), Subscription.created_at.desc())
            .limit(50)
        )
    )
    if not subscriptions:
        return None
    current = next(
        (
            subscription
            for subscription in subscriptions
            if subscription_status(subscription, today) == "active"
        ),
        None,
    )
    scheduled = min(
        (
            subscription
            for subscription in subscriptions
            if subscription_status(subscription, today) == "scheduled"
        ),
        key=lambda subscription: subscription.starts_on,
        default=None,
    )
    latest = current or scheduled or subscriptions[0]
    return MemberMembership(
        id=latest.id,
        plan_name=latest.plan_name,
        monthly_price_kes=latest.monthly_price_kes,
        starts_on=latest.starts_on,
        expires_on=latest.expires_on,
        status=subscription_status(latest, today),
    )


@router.get("/me", operation_id="getCurrentMemberProfile", response_model=MemberProfileResponse)
def get_member_profile(
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> MemberProfileResponse:
    today = gym_now(session).date()
    return MemberProfileResponse(
        id=member.id,
        member_number=member.member_number,
        full_name=member.full_name,
        email=member.email,
        phone=member.phone,
        status=member.status,
        registered_at=member.registered_at,
        qr_token=member.qr_token,
        membership=_latest_membership(session, member, today),
        check_ins_this_month=_check_ins_this_month(session, member, today),
    )


def _workout_response(
    session: Session, assignment: WorkoutAssignment
) -> MemberWorkoutResponse:
    program = session.get(WorkoutProgram, assignment.program_id)
    if program is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "An assigned workout is unavailable", "code": "workout_program_missing"},
        )
    exercises = list(
        session.scalars(
            select(WorkoutExercise)
            .where(WorkoutExercise.program_id == program.id)
            .order_by(WorkoutExercise.position)
        )
    )
    sessions = list(
        session.scalars(
            select(WorkoutSession)
            .where(WorkoutSession.assignment_id == assignment.id)
            .order_by(WorkoutSession.session_date.desc())
            .limit(20)
        )
    )
    return MemberWorkoutResponse(
        id=assignment.id,
        program_id=program.id,
        program_name=program.name,
        goal=program.goal,
        description=program.description,
        starts_on=assignment.starts_on,
        status=assignment.status,
        notes=assignment.notes,
        recommended_days_per_week=program.recommended_days_per_week,
        expected_session_minutes=program.expected_session_minutes,
        exercises=[
            MemberWorkoutExercise(
                id=exercise.id,
                position=exercise.position,
                name=exercise.name,
                sets=exercise.sets,
                repetitions=exercise.repetitions,
                duration_seconds=exercise.duration_seconds,
                rest_seconds=exercise.rest_seconds,
            )
            for exercise in exercises
        ],
        sessions=[
            MemberWorkoutSessionResponse.model_validate(
                {
                    "id": workout_session.id,
                    "session_date": workout_session.session_date,
                    "status": workout_session.status,
                    "exercises": workout_session.exercises,
                    "recorded_at": workout_session.recorded_at,
                    "completed_at": workout_session.completed_at,
                }
            )
            for workout_session in sessions
        ],
    )


@router.get("/workouts", operation_id="listMyWorkouts", response_model=list[MemberWorkoutResponse])
def list_member_workouts(
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> list[MemberWorkoutResponse]:
    today = gym_now(session).date()
    assignments = session.scalars(
        select(WorkoutAssignment)
        .where(
            WorkoutAssignment.member_id == member.id,
            WorkoutAssignment.status != "cancelled",
            WorkoutAssignment.starts_on <= today,
        )
        .order_by(WorkoutAssignment.starts_on.desc(), WorkoutAssignment.created_at.desc())
        .limit(50)
    )
    return [_workout_response(session, assignment) for assignment in assignments]


@router.post(
    "/workouts/{assignment_id}/sessions",
    operation_id="saveMyWorkoutSession",
    response_model=MemberWorkoutSessionResponse,
)
def save_member_workout_session(
    assignment_id: UUID,
    data: MemberWorkoutSessionInput,
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> MemberWorkoutSessionResponse:
    assignment = session.scalar(
        select(WorkoutAssignment)
        .where(
            WorkoutAssignment.id == assignment_id,
            WorkoutAssignment.member_id == member.id,
            WorkoutAssignment.status != "cancelled",
        )
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Workout assignment not found", "code": "workout_assignment_not_found"},
        )
    allowed_ids = set(
        session.scalars(
            select(WorkoutExercise.id).where(
                WorkoutExercise.program_id == assignment.program_id
            )
        )
    )
    submitted_ids = {item.exercise_id for item in data.exercises}
    if not submitted_ids.issubset(allowed_ids):
        raise HTTPException(
            status_code=422,
            detail={"error": "Session contains an exercise outside this workout", "code": "invalid_workout_exercise"},
        )

    today = gym_now(session).date()
    all_exercises_complete = (
        bool(allowed_ids)
        and submitted_ids == allowed_ids
        and all(item.completed for item in data.exercises)
    )
    now = datetime.now(timezone.utc)
    workout_session = session.scalar(
        select(WorkoutSession)
        .where(
            WorkoutSession.assignment_id == assignment.id,
            WorkoutSession.session_date == today,
        )
        .with_for_update()
    )
    if workout_session is None:
        workout_session = WorkoutSession(
            assignment_id=assignment.id,
            member_id=member.id,
            session_date=today,
        )
        session.add(workout_session)
    workout_session.status = "completed" if all_exercises_complete else "in_progress"
    workout_session.exercises = [
        item.model_dump(mode="json") for item in data.exercises
    ]
    workout_session.completed_at = now if all_exercises_complete else None
    if all_exercises_complete:
        assignment.status = "completed"
    elif assignment.status == "assigned":
        assignment.status = "in_progress"

    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(workout_session)
    return MemberWorkoutSessionResponse.model_validate(workout_session)


@router.get("/events", operation_id="listMyEvents", response_model=list[MemberEventResponse])
def list_member_events(
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> list[MemberEventResponse]:
    now = datetime.now(timezone.utc)
    rows = session.execute(
        select(GymEvent, StaffUser.name, EventRegistration.status)
        .outerjoin(
            StaffUser,
            GymEvent.instructor_staff_id == StaffUser.id,
        )
        .outerjoin(
            EventRegistration,
            and_(
                EventRegistration.event_id == GymEvent.id,
                EventRegistration.member_id == member.id,
            ),
        )
        .where(GymEvent.status == "published", GymEvent.ends_at >= now)
        .order_by(GymEvent.starts_at)
        .limit(100)
    ).all()
    responses = []
    for event, instructor_name, registration_status in rows:
        base = _event_response(session, event, instructor_name)
        responses.append(
            MemberEventResponse(
                **base.model_dump(),
                registration_status=registration_status,
            )
        )
    return responses


@router.post(
    "/events/{event_id}/registration",
    operation_id="registerMyselfForEvent",
    response_model=EventRegistrationResponse,
    status_code=201,
)
def register_myself_for_event(
    event_id: UUID,
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> EventRegistrationResponse:
    registration = register_event_member(session, event_id, member)
    return _registration_response(registration, member)


@router.delete(
    "/events/{event_id}/registration",
    operation_id="cancelMyEventRegistration",
    response_model=EventRegistrationResponse,
)
def cancel_my_event_registration(
    event_id: UUID,
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> EventRegistrationResponse:
    event = session.scalar(
        select(GymEvent).where(GymEvent.id == event_id).with_for_update()
    )
    if event is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Event not found", "code": "event_not_found"},
        )
    now = datetime.now(timezone.utc)
    if event.status != "published" or _stored_utc(event.starts_at) <= now:
        raise HTTPException(
            status_code=409,
            detail={"error": "Registration can no longer be cancelled", "code": "event_registration_closed"},
        )
    registration = session.scalar(
        select(EventRegistration)
        .where(
            EventRegistration.event_id == event_id,
            EventRegistration.member_id == member.id,
            EventRegistration.status == "confirmed",
        )
        .with_for_update()
    )
    if registration is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Active event registration not found", "code": "event_registration_not_found"},
        )
    registration.status = "cancelled"
    event.confirmed_count = max(event.confirmed_count - 1, 0)
    session.commit()
    session.refresh(registration)
    return _registration_response(registration, member)


@router.get("/progress", operation_id="getMyProgress", response_model=MemberProgressResponse)
def get_member_progress(
    member: Member = Depends(get_current_member),
    session: Session = Depends(get_member_db),
) -> MemberProgressResponse:
    today = gym_now(session).date()
    month_start = date(today.year, today.month, 1)
    month_end = next_calendar_month(month_start)
    assessments = session.scalars(
        select(FitnessAssessment)
        .where(FitnessAssessment.member_id == member.id)
        .order_by(FitnessAssessment.recorded_at.desc())
        .limit(100)
    )
    check_ins = _check_ins_this_month(session, member, today)
    completed_workouts = int(
        session.scalar(
            select(func.count(WorkoutSession.id)).where(
                WorkoutSession.member_id == member.id,
                WorkoutSession.session_date >= month_start,
                WorkoutSession.session_date < month_end,
                WorkoutSession.status == "completed",
            )
        )
        or 0
    )
    return MemberProgressResponse(
        assessments=[
            FitnessAssessmentHistoryItem(
                id=item.id,
                recorded_at=item.recorded_at,
                weight_kg=item.weight_kg,
                height_cm=item.height_cm,
                bmi=item.bmi,
                body_fat_percent=item.body_fat_percent,
                muscle_percent=item.muscle_percent,
                visceral_fat_level=item.visceral_fat_level,
            )
            for item in assessments
        ],
        check_ins_this_month=check_ins,
        workouts_this_month=completed_workouts,
    )
