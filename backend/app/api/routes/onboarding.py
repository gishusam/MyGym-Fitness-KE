from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner_or_receptionist, require_owner_or_trainer
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.member import Member, MemberStatus
from backend.app.models.member_onboarding import MemberFitnessProfile
from backend.app.models.staff_user import StaffUser
from backend.app.models.workout import (
    WorkoutAssignment,
    WorkoutExercise,
    WorkoutProgram,
)
from backend.app.schemas.onboarding import (
    MemberOnboardingInput,
    MemberOnboardingView,
    OnboardingAssignmentInput,
    OnboardingLinkResponse,
    OnboardingProgram,
    OnboardingRevocationResponse,
    OnboardingReviewItem,
)
from backend.app.schemas.workspaces import (
    WorkoutAssignmentResponse,
    WorkoutExerciseResponse,
)
from backend.app.services.onboarding import (
    find_active_onboarding_token,
    issue_member_onboarding_token,
    revoke_member_onboarding_tokens,
)

router = APIRouter(tags=["member onboarding"])
_EXPERIENCE_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": "This onboarding link is invalid or no longer available", "code": "onboarding_link_unavailable"},
    )


def _questionnaire(profile: MemberFitnessProfile) -> MemberOnboardingInput:
    return MemberOnboardingInput(
        primary_goal=profile.primary_goal,
        experience=profile.experience,
        available_days_per_week=profile.available_days_per_week,
        session_duration_minutes=profile.session_duration_minutes,
        equipment_preferences=profile.equipment_preferences or [],
        limitations=profile.limitations,
        notes=profile.notes,
    )


def _match_reasons(
    program: WorkoutProgram, questionnaire: MemberOnboardingInput
) -> list[str]:
    reasons = [
        "Supports your selected goal.",
        "Accepts your current training experience.",
    ]
    if program.recommended_days_per_week == questionnaire.available_days_per_week:
        reasons.append(
            f"Matches your {questionnaire.available_days_per_week} available training days."
        )
    else:
        reasons.append(
            f"Fits within your {questionnaire.available_days_per_week} available training days."
        )
    reasons.append(
        f"Sessions take about {program.expected_session_minutes} minutes, within your "
        f"{questionnaire.session_duration_minutes}-minute limit."
    )
    if program.equipment_requirements:
        reasons.append("The equipment it needs is in your selected preferences.")
    else:
        reasons.append("It does not require specific equipment.")
    if program.trainer_review_required:
        reasons.append("A trainer must review this program before it is assigned.")
    return reasons


def _program_summary(
    session: Session,
    program_id: UUID | None,
    questionnaire: MemberOnboardingInput,
) -> OnboardingProgram | None:
    if program_id is None:
        return None
    program = session.get(WorkoutProgram, program_id)
    if program is None or program.status != "active":
        return None
    exercises = session.scalars(
        select(WorkoutExercise)
        .where(WorkoutExercise.program_id == program.id)
        .order_by(WorkoutExercise.position)
    )
    return OnboardingProgram(
        id=program.id,
        name=program.name,
        goal=program.goal,
        description=program.description,
        recommended_days_per_week=program.recommended_days_per_week,
        expected_session_minutes=program.expected_session_minutes,
        equipment_requirements=program.equipment_requirements or [],
        trainer_review_required=program.trainer_review_required,
        exercises=[
            WorkoutExerciseResponse(
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
        match_reasons=_match_reasons(program, questionnaire),
    )


def _recommended_programs(
    session: Session, questionnaire: MemberOnboardingInput
) -> list[WorkoutProgram]:
    # A free-text limitation cannot be safely mapped to this program catalog.
    # Send that case to a trainer instead of guessing about exercise safety.
    if questionnaire.limitations:
        return []

    eligible: list[WorkoutProgram] = []
    programs = session.scalars(
        select(WorkoutProgram)
        .where(WorkoutProgram.status == "active")
        .order_by(WorkoutProgram.name, WorkoutProgram.id)
    )
    equipment = set(questionnaire.equipment_preferences)
    for program in programs:
        if questionnaire.primary_goal not in (program.goals_supported or []):
            continue
        minimum = _EXPERIENCE_ORDER.get(program.minimum_experience, 99)
        maximum = _EXPERIENCE_ORDER.get(program.maximum_experience, -1)
        experience = _EXPERIENCE_ORDER[questionnaire.experience]
        if not minimum <= experience <= maximum:
            continue
        if program.recommended_days_per_week > questionnaire.available_days_per_week:
            continue
        if program.expected_session_minutes > questionnaire.session_duration_minutes:
            continue
        required_equipment = set(program.equipment_requirements or [])
        if "full_gym" not in equipment and not required_equipment.issubset(equipment):
            continue
        eligible.append(program)

    def priority(program: WorkoutProgram) -> tuple[int, int, int, str]:
        beginner_preference = (
            0
            if questionnaire.experience != "beginner"
            or program.minimum_experience == "beginner"
            else 1
        )
        day_gap = questionnaire.available_days_per_week - program.recommended_days_per_week
        duration_gap = questionnaire.session_duration_minutes - program.expected_session_minutes
        return beginner_preference, day_gap, duration_gap, program.name.casefold()

    return sorted(eligible, key=priority)[:3]


def _view(
    session: Session,
    member: Member,
    expires_at: datetime,
    profile: MemberFitnessProfile | None,
) -> MemberOnboardingView:
    if profile is None:
        return MemberOnboardingView(
            first_name=member.full_name.split()[0],
            expires_at=expires_at,
            submitted=False,
        )

    questionnaire = _questionnaire(profile)
    recommendation = _program_summary(
        session, profile.recommended_program_id, questionnaire
    )
    alternatives = [
        summary
        for program_id in (profile.alternative_program_ids or [])
        if (summary := _program_summary(session, UUID(str(program_id)), questionnaire))
        is not None
    ]
    assigned = _program_summary(session, profile.final_program_id, questionnaire)
    no_match_reason = None
    if recommendation is None:
        if questionnaire.limitations:
            no_match_reason = (
                "A trainer will review the limitation you shared and help choose a suitable program."
            )
        elif profile.review_status == "awaiting_review":
            no_match_reason = (
                "We could not find a saved program that fits every answer. A trainer will help choose one."
            )
    return MemberOnboardingView(
        first_name=member.full_name.split()[0],
        expires_at=expires_at,
        submitted=True,
        questionnaire=questionnaire,
        review_status=profile.review_status,
        recommendation=recommendation,
        alternatives=alternatives,
        no_match_reason=no_match_reason,
        assigned_program=assigned,
    )


@router.post(
    "/members/{member_id}/onboarding-link",
    operation_id="createMemberOnboardingLink",
    response_model=OnboardingLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_member_onboarding_link(
    member_id: UUID,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> OnboardingLinkResponse:
    member = session.get(Member, member_id)
    if member is None or member.status != MemberStatus.ACTIVE.value:
        raise _not_found()
    token, expires_at = issue_member_onboarding_token(session, member)
    session.commit()
    return OnboardingLinkResponse(token=token, expires_at=expires_at)


@router.post(
    "/members/{member_id}/onboarding-link/revoke",
    operation_id="revokeMemberOnboardingLink",
    response_model=OnboardingRevocationResponse,
)
def revoke_member_onboarding_link(
    member_id: UUID,
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> OnboardingRevocationResponse:
    if session.get(Member, member_id) is None:
        raise _not_found()
    revoked = revoke_member_onboarding_tokens(session, member_id)
    session.commit()
    return OnboardingRevocationResponse(revoked=revoked)


@router.get(
    "/public/onboarding/{token}",
    operation_id="getPublicMemberOnboarding",
    response_model=MemberOnboardingView,
)
def get_public_member_onboarding(
    token: str,
    session: Session = Depends(get_db),
) -> MemberOnboardingView:
    token_record = find_active_onboarding_token(session, token)
    if token_record is None:
        raise _not_found()
    member = session.get(Member, token_record.member_id)
    if member is None or member.status != MemberStatus.ACTIVE.value:
        raise _not_found()
    profile = session.scalar(
        select(MemberFitnessProfile).where(
            MemberFitnessProfile.member_id == member.id
        )
    )
    return _view(session, member, token_record.expires_at, profile)


@router.post(
    "/public/onboarding/{token}",
    operation_id="submitPublicMemberOnboarding",
    response_model=MemberOnboardingView,
)
def submit_public_member_onboarding(
    token: str,
    data: MemberOnboardingInput,
    session: Session = Depends(get_db),
) -> MemberOnboardingView:
    token_record = find_active_onboarding_token(session, token)
    if token_record is None:
        raise _not_found()
    member = session.get(Member, token_record.member_id)
    if member is None or member.status != MemberStatus.ACTIVE.value:
        raise _not_found()

    profile = session.scalar(
        select(MemberFitnessProfile)
        .where(MemberFitnessProfile.member_id == member.id)
        .with_for_update()
    )
    if profile is not None and profile.review_status == "trainer_approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Your trainer has already assigned your program. Contact the gym if your details need updating.",
                "code": "onboarding_already_reviewed",
            },
        )

    matches = _recommended_programs(session, data)
    if profile is None:
        profile = MemberFitnessProfile(
            id=uuid4(),
            member_id=member.id,
            primary_goal=data.primary_goal,
            experience=data.experience,
            available_days_per_week=data.available_days_per_week,
            session_duration_minutes=data.session_duration_minutes,
            equipment_preferences=data.equipment_preferences,
            limitations=data.limitations,
            notes=data.notes,
        )
        session.add(profile)
    else:
        profile.primary_goal = data.primary_goal
        profile.experience = data.experience
        profile.available_days_per_week = data.available_days_per_week
        profile.session_duration_minutes = data.session_duration_minutes
        profile.equipment_preferences = data.equipment_preferences
        profile.limitations = data.limitations
        profile.notes = data.notes

    profile.review_status = "awaiting_review"
    profile.recommended_program_id = matches[0].id if matches else None
    profile.alternative_program_ids = [str(program.id) for program in matches[1:]]
    profile.final_program_id = None
    profile.workout_assignment_id = None
    profile.reviewed_by_staff_id = None
    profile.reviewed_at = None
    profile.submitted_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(profile)
    return _view(session, member, token_record.expires_at, profile)


@router.get(
    "/onboarding/reviews",
    operation_id="listMemberOnboardingReviews",
    response_model=list[OnboardingReviewItem],
)
def list_member_onboarding_reviews(
    _staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> list[OnboardingReviewItem]:
    profiles = session.scalars(
        select(MemberFitnessProfile)
        .where(MemberFitnessProfile.review_status == "awaiting_review")
        .order_by(MemberFitnessProfile.submitted_at, MemberFitnessProfile.id)
        .limit(200)
    )
    items: list[OnboardingReviewItem] = []
    for profile in profiles:
        member = session.get(Member, profile.member_id)
        if member is None or member.status != MemberStatus.ACTIVE.value:
            continue
        questionnaire = _questionnaire(profile)
        items.append(
            OnboardingReviewItem(
                member_id=member.id,
                member_name=member.full_name,
                member_number=member.member_number,
                primary_goal=profile.primary_goal,
                experience=profile.experience,
                available_days_per_week=profile.available_days_per_week,
                session_duration_minutes=profile.session_duration_minutes,
                equipment_preferences=profile.equipment_preferences or [],
                limitations=profile.limitations,
                notes=profile.notes,
                recommendation=_program_summary(
                    session, profile.recommended_program_id, questionnaire
                ),
                alternatives=[
                    summary
                    for program_id in (profile.alternative_program_ids or [])
                    if (summary := _program_summary(
                        session, UUID(str(program_id)), questionnaire
                    ))
                    is not None
                ],
                submitted_at=profile.submitted_at,
            )
        )
    return items


@router.post(
    "/onboarding/reviews/{member_id}/assign",
    operation_id="assignReviewedOnboardingProgram",
    response_model=WorkoutAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_reviewed_onboarding_program(
    member_id: UUID,
    data: OnboardingAssignmentInput,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> WorkoutAssignmentResponse:
    profile = session.scalar(
        select(MemberFitnessProfile)
        .where(MemberFitnessProfile.member_id == member_id)
        .with_for_update()
    )
    if profile is None or profile.review_status != "awaiting_review":
        raise HTTPException(
            status_code=404,
            detail={"error": "Pending onboarding review not found", "code": "onboarding_review_not_found"},
        )
    member = session.get(Member, member_id)
    program = session.get(WorkoutProgram, data.program_id)
    if member is None or member.status != MemberStatus.ACTIVE.value:
        raise HTTPException(
            status_code=404,
            detail={"error": "Active member not found", "code": "member_not_found"},
        )
    if program is None or program.status != "active":
        raise HTTPException(
            status_code=404,
            detail={"error": "Active workout program not found", "code": "workout_program_not_found"},
        )

    assignment = WorkoutAssignment(
        id=uuid4(),
        program_id=program.id,
        member_id=member.id,
        assigned_by_staff_id=staff.id,
        starts_on=data.starts_on,
        status="assigned",
        notes=data.notes,
    )
    session.add(assignment)
    session.flush()  # Persist assignment before updating its FK reference.
    profile.review_status = "trainer_approved"
    profile.final_program_id = program.id
    profile.workout_assignment_id = assignment.id
    profile.reviewed_by_staff_id = staff.id
    profile.reviewed_at = datetime.now(timezone.utc)
    session.add(
        AuditLog(
            actor_staff_id=staff.id,
            action="workout.onboarding_program_assigned",
            entity_type="member_fitness_profile",
            entity_id=str(profile.id),
            details={
                "member_id": str(member.id),
                "program_id": str(program.id),
                "assignment_id": str(assignment.id),
            },
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "This member already has an active assignment for the selected program",
                "code": "workout_assignment_conflict",
            },
        )
    session.refresh(assignment)
    return WorkoutAssignmentResponse(
        id=assignment.id,
        program_id=program.id,
        program_name=program.name,
        goal=program.goal,
        member_id=member.id,
        member_number=member.member_number,
        member_name=member.full_name,
        starts_on=assignment.starts_on,
        status=assignment.status,
        notes=assignment.notes,
        created_at=assignment.created_at,
    )
