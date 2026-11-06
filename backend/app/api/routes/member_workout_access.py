from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner_or_trainer
from backend.app.db.session import get_db
from backend.app.models.member import Member
from backend.app.models.member_workout_link import MemberWorkoutLink
from backend.app.models.membership import Subscription
from backend.app.models.staff_user import StaffUser
from backend.app.models.workout import WorkoutAssignment, WorkoutExercise, WorkoutProgram

router = APIRouter(tags=['member workout access'])
LINK_LIFETIME = timedelta(days=180)
ACTIVE_ASSIGNMENTS = ('assigned', 'in_progress')


def missing_link() -> HTTPException:
    return HTTPException(status_code=404, detail={'error': 'This workout link is unavailable or has expired', 'code': 'workout_link_unavailable'})


def lookup(session: Session, token: str) -> tuple[WorkoutAssignment, WorkoutProgram, Member]:
    if len(token) > 256:
        raise missing_link()
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    link = session.scalar(select(MemberWorkoutLink).where(MemberWorkoutLink.token_hash == digest, MemberWorkoutLink.revoked_at.is_(None)))
    if link is None:
        raise missing_link()
    expiry = link.expires_at.replace(tzinfo=timezone.utc) if link.expires_at.tzinfo is None else link.expires_at
    if expiry <= datetime.now(timezone.utc):
        raise missing_link()
    assignment = session.get(WorkoutAssignment, link.assignment_id)
    if assignment is None or assignment.status not in ACTIVE_ASSIGNMENTS:
        raise missing_link()
    member = session.get(Member, assignment.member_id)
    program = session.get(WorkoutProgram, assignment.program_id)
    if member is None or member.status != 'active' or program is None:
        raise missing_link()
    today = datetime.now(ZoneInfo('Africa/Nairobi')).date()
    active_membership = session.scalar(select(Subscription.id).where(
        Subscription.member_id == member.id,
        Subscription.status != 'cancelled',
        Subscription.starts_on <= today,
        Subscription.expires_on >= today,
    ).limit(1))
    if active_membership is None:
        raise HTTPException(status_code=403, detail={'error': 'Your gym membership is not currently active. Contact reception for assistance.', 'code': 'membership_not_active'})
    return assignment, program, member


def workout_document(session: Session, assignment: WorkoutAssignment, program: WorkoutProgram, member: Member) -> dict:
    exercises = session.scalars(select(WorkoutExercise).where(WorkoutExercise.program_id == program.id).order_by(WorkoutExercise.position)).all()
    return {
        'memberFirstName': member.full_name.split()[0],
        'memberName': member.full_name,
        'programName': program.name,
        'goal': program.goal,
        'description': program.description,
        'daysPerWeek': program.recommended_days_per_week,
        'sessionMinutes': program.expected_session_minutes,
        'startsOn': assignment.starts_on.isoformat(),
        'trainerNotes': assignment.notes,
        'exercises': [{'name': x.name, 'sets': x.sets, 'repetitions': x.repetitions, 'durationSeconds': x.duration_seconds, 'restSeconds': x.rest_seconds} for x in exercises],
        'trainerGuidance': 'Ask your on-site trainer to demonstrate movements, adjust uncomfortable exercises and support your progress.',
    }


@router.post('/workout-assignments/{assignment_id}/share-link', operation_id='createWorkoutShareLink')
def create_workout_share_link(assignment_id: UUID, _staff: StaffUser = Depends(require_owner_or_trainer), session: Session = Depends(get_db)) -> dict:
    assignment = session.scalar(select(WorkoutAssignment).where(WorkoutAssignment.id == assignment_id).with_for_update())
    if assignment is None or assignment.status not in ACTIVE_ASSIGNMENTS:
        raise HTTPException(status_code=404, detail={'error': 'Active workout assignment not found', 'code': 'assignment_unavailable'})
    member = session.get(Member, assignment.member_id)
    program = session.get(WorkoutProgram, assignment.program_id)
    if member is None or member.status != 'active' or program is None:
        raise missing_link()
    now = datetime.now(timezone.utc)
    session.execute(update(MemberWorkoutLink).where(MemberWorkoutLink.assignment_id == assignment_id, MemberWorkoutLink.revoked_at.is_(None)).values(revoked_at=now))
    raw = secrets.token_urlsafe(32)
    session.add(MemberWorkoutLink(id=uuid4(), assignment_id=assignment_id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=now + LINK_LIFETIME))
    session.commit()
    return {'assignmentId': str(assignment.id), 'token': raw, 'memberName': member.full_name, 'phone': member.phone, 'programName': program.name, 'daysPerWeek': program.recommended_days_per_week, 'sessionMinutes': program.expected_session_minutes, 'expiresAt': (now + LINK_LIFETIME).isoformat()}


@router.post('/workout-assignments/{assignment_id}/share-link/revoke', operation_id='revokeWorkoutShareLink')
def revoke_workout_share_link(assignment_id: UUID, _staff: StaffUser = Depends(require_owner_or_trainer), session: Session = Depends(get_db)) -> dict:
    result = session.execute(update(MemberWorkoutLink).where(MemberWorkoutLink.assignment_id == assignment_id, MemberWorkoutLink.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
    session.commit()
    return {'revoked': bool(result.rowcount)}


@router.get('/public/workout/{token}', operation_id='getPublicMemberWorkout')
def get_public_workout(token: str, session: Session = Depends(get_db)) -> dict:
    assignment, program, member = lookup(session, token)
    return workout_document(session, assignment, program, member)


@router.get('/public/workout/{token}/pdf', operation_id='downloadPublicMemberWorkout')
def download_public_workout(token: str, session: Session = Depends(get_db)) -> Response:
    assignment, program, member = lookup(session, token)
    from backend.app.services.workout_pdf import create_workout_pdf
    pdf = create_workout_pdf(workout_document(session, assignment, program, member))
    return Response(content=pdf, media_type='application/pdf', headers={
        'Content-Disposition': 'attachment; filename="mygym-workout.pdf"',
        'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
    })
