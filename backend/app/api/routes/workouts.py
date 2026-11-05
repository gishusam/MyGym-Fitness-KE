from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner_or_trainer
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.member import Member, MemberStatus
from backend.app.models.staff_user import StaffUser
from backend.app.models.workout import (
    WorkoutAssignment,
    WorkoutExercise,
    WorkoutProgram,
    WorkoutResource,
)
from backend.app.schemas.workspaces import (
    WorkoutAssignmentInput,
    WorkoutAssignmentResponse,
    WorkoutAssignmentUpdate,
    WorkoutExerciseInput,
    WorkoutExerciseResponse,
    WorkoutProgramInput,
    WorkoutProgramResponse,
    WorkoutProgramUpdate,
    WorkoutResourceResponse,
)
from backend.app.services.private_uploads import (
    delete_upload,
    save_request_upload,
    upload_path,
)

router = APIRouter(tags=["workouts"])


def _audit(
    session: Session,
    staff: StaffUser,
    action: str,
    entity_type: str,
    entity_id: UUID,
    details: dict,
) -> None:
    session.add(
        AuditLog(
            actor_staff_id=staff.id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
        )
    )


def _exercise_response(exercise: WorkoutExercise) -> WorkoutExerciseResponse:
    return WorkoutExerciseResponse(
        id=exercise.id,
        position=exercise.position,
        name=exercise.name,
        sets=exercise.sets,
        repetitions=exercise.repetitions,
        duration_seconds=exercise.duration_seconds,
        rest_seconds=exercise.rest_seconds,
    )


def _resource_response(resource: WorkoutResource) -> WorkoutResourceResponse:
    return WorkoutResourceResponse(
        id=resource.id,
        original_filename=resource.original_filename,
        media_type=resource.media_type,
        size_bytes=resource.size_bytes,
        created_at=resource.created_at,
        download_url=f"/api/workout-resources/{resource.id}/download",
    )


def _program_response(
    session: Session, program: WorkoutProgram
) -> WorkoutProgramResponse:
    exercises = session.scalars(
        select(WorkoutExercise)
        .where(WorkoutExercise.program_id == program.id)
        .order_by(WorkoutExercise.position)
    )
    resources = session.scalars(
        select(WorkoutResource)
        .where(WorkoutResource.program_id == program.id)
        .order_by(WorkoutResource.created_at, WorkoutResource.id)
    )
    return WorkoutProgramResponse(
        id=program.id,
        name=program.name,
        goal=program.goal,
        description=program.description,
        status=program.status,
        created_at=program.created_at,
        updated_at=program.updated_at,
        exercises=[_exercise_response(item) for item in exercises],
        resources=[_resource_response(item) for item in resources],
    )


def _assignment_response(
    session: Session, assignment: WorkoutAssignment
) -> WorkoutAssignmentResponse:
    program = session.get(WorkoutProgram, assignment.program_id)
    member = session.get(Member, assignment.member_id)
    if program is None or member is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Workout assignment not found", "code": "workout_assignment_not_found"},
        )
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


def _exercise_rows(
    program_id: UUID, exercises: list[WorkoutExerciseInput]
) -> list[WorkoutExercise]:
    return [
        WorkoutExercise(
            id=uuid4(),
            program_id=program_id,
            position=index,
            **exercise.model_dump(),
        )
        for index, exercise in enumerate(exercises)
    ]


@router.get("/workouts", operation_id="listWorkoutPrograms", response_model=list[WorkoutProgramResponse])
def list_workout_programs(
    include_archived: bool = Query(default=False, alias="includeArchived"),
    _staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> list[WorkoutProgramResponse]:
    stmt = select(WorkoutProgram)
    if not include_archived:
        stmt = stmt.where(WorkoutProgram.status == "active")
    programs = session.scalars(
        stmt.order_by(WorkoutProgram.updated_at.desc(), WorkoutProgram.name).limit(100)
    )
    return [_program_response(session, program) for program in programs]


@router.post(
    "/workouts",
    operation_id="createWorkoutProgram",
    response_model=WorkoutProgramResponse,
    status_code=201,
)
def create_workout_program(
    data: WorkoutProgramInput,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> WorkoutProgramResponse:
    program = WorkoutProgram(
        id=uuid4(),
        name=data.name,
        goal=data.goal,
        description=data.description,
        status="active",
        created_by_staff_id=staff.id,
    )
    session.add(program)
    session.flush()
    session.add_all(_exercise_rows(program.id, data.exercises))
    _audit(
        session,
        staff,
        "workout.program_created",
        "workout_program",
        program.id,
        {"name": program.name},
    )
    session.commit()
    session.refresh(program)
    return _program_response(session, program)


@router.patch(
    "/workouts/{program_id}",
    operation_id="updateWorkoutProgram",
    response_model=WorkoutProgramResponse,
)
def update_workout_program(
    program_id: UUID,
    changes: WorkoutProgramUpdate,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> WorkoutProgramResponse:
    program = session.scalar(
        select(WorkoutProgram).where(WorkoutProgram.id == program_id).with_for_update()
    )
    if program is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Workout program not found", "code": "workout_program_not_found"},
        )
    updates = changes.model_dump(exclude_unset=True, exclude={"exercises"})
    if any(value is None for key, value in updates.items() if key != "description"):
        raise HTTPException(
            status_code=422,
            detail={"error": "Workout name, goal and status cannot be cleared", "code": "invalid_workout_update"},
        )
    if "exercises" in changes.model_fields_set and changes.exercises is None:
        raise HTTPException(
            status_code=422,
            detail={"error": "Workout exercises cannot be cleared", "code": "invalid_workout_update"},
        )
    for field, value in updates.items():
        setattr(program, field, value)
    if changes.exercises is not None:
        session.execute(
            delete(WorkoutExercise).where(WorkoutExercise.program_id == program.id)
        )
        session.add_all(_exercise_rows(program.id, changes.exercises))
    _audit(
        session,
        staff,
        "workout.program_updated",
        "workout_program",
        program.id,
        {"fields": sorted(changes.model_fields_set)},
    )
    session.commit()
    session.refresh(program)
    return _program_response(session, program)


@router.get(
    "/workout-assignments",
    operation_id="listWorkoutAssignments",
    response_model=list[WorkoutAssignmentResponse],
)
def list_workout_assignments(
    member_id: UUID | None = Query(default=None, alias="memberId"),
    _staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> list[WorkoutAssignmentResponse]:
    stmt = select(WorkoutAssignment)
    if member_id is not None:
        stmt = stmt.where(WorkoutAssignment.member_id == member_id)
    assignments = session.scalars(
        stmt.order_by(WorkoutAssignment.starts_on.desc(), WorkoutAssignment.created_at.desc()).limit(200)
    )
    return [_assignment_response(session, assignment) for assignment in assignments]


@router.post(
    "/workouts/{program_id}/assignments",
    operation_id="assignWorkoutProgram",
    response_model=WorkoutAssignmentResponse,
    status_code=201,
)
def assign_workout_program(
    program_id: UUID,
    data: WorkoutAssignmentInput,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> WorkoutAssignmentResponse:
    program = session.scalar(
        select(WorkoutProgram).where(WorkoutProgram.id == program_id).with_for_update()
    )
    if program is None or program.status != "active":
        raise HTTPException(
            status_code=404,
            detail={"error": "Active workout program not found", "code": "workout_program_not_found"},
        )
    member = session.get(Member, data.member_id)
    if member is None or member.status != MemberStatus.ACTIVE.value:
        raise HTTPException(
            status_code=404,
            detail={"error": "Active member not found", "code": "member_not_found"},
        )
    existing = session.scalar(
        select(WorkoutAssignment.id).where(
            WorkoutAssignment.program_id == program.id,
            WorkoutAssignment.member_id == member.id,
            WorkoutAssignment.status.in_(("assigned", "in_progress")),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "This program is already active for the member", "code": "workout_already_assigned"},
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
    _audit(
        session,
        staff,
        "workout.program_assigned",
        "workout_assignment",
        assignment.id,
        {"program_id": str(program.id), "member_id": str(member.id)},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "The program could not be assigned", "code": "workout_assignment_conflict"},
        ) from None
    session.refresh(assignment)
    return _assignment_response(session, assignment)


@router.patch(
    "/workout-assignments/{assignment_id}",
    operation_id="updateWorkoutAssignment",
    response_model=WorkoutAssignmentResponse,
)
def update_workout_assignment(
    assignment_id: UUID,
    changes: WorkoutAssignmentUpdate,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> WorkoutAssignmentResponse:
    assignment = session.scalar(
        select(WorkoutAssignment)
        .where(WorkoutAssignment.id == assignment_id)
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Workout assignment not found", "code": "workout_assignment_not_found"},
        )
    updates = changes.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is None:
        raise HTTPException(
            status_code=422,
            detail={"error": "Assignment status cannot be cleared", "code": "invalid_assignment_update"},
        )
    if updates.get("status") in {"assigned", "in_progress"}:
        duplicate_active = session.scalar(
            select(WorkoutAssignment.id).where(
                WorkoutAssignment.program_id == assignment.program_id,
                WorkoutAssignment.member_id == assignment.member_id,
                WorkoutAssignment.id != assignment.id,
                WorkoutAssignment.status.in_(("assigned", "in_progress")),
            )
        )
        if duplicate_active is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "This program is already active for the member",
                    "code": "workout_already_assigned",
                },
            )
    for field, value in updates.items():
        setattr(assignment, field, value)
    _audit(
        session,
        staff,
        "workout.assignment_updated",
        "workout_assignment",
        assignment.id,
        {"fields": sorted(changes.model_fields_set)},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "This program is already active for the member",
                "code": "workout_already_assigned",
            },
        ) from None
    session.refresh(assignment)
    return _assignment_response(session, assignment)


@router.post(
    "/workouts/{program_id}/resources",
    operation_id="uploadWorkoutResource",
    response_model=WorkoutResourceResponse,
    status_code=201,
)
async def upload_workout_resource(
    program_id: UUID,
    request: Request,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> WorkoutResourceResponse:
    program = session.scalar(
        select(WorkoutProgram).where(WorkoutProgram.id == program_id).with_for_update()
    )
    if program is None or program.status != "active":
        raise HTTPException(
            status_code=404,
            detail={"error": "Active workout program not found", "code": "workout_program_not_found"},
        )
    storage_key, filename, media_type, size = await save_request_upload(request)
    resource = WorkoutResource(
        id=uuid4(),
        program_id=program.id,
        original_filename=filename,
        media_type=media_type,
        storage_key=storage_key,
        size_bytes=size,
        uploaded_by_staff_id=staff.id,
    )
    session.add(resource)
    _audit(
        session,
        staff,
        "workout.resource_uploaded",
        "workout_resource",
        resource.id,
        {"program_id": str(program.id), "media_type": media_type, "size_bytes": size},
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        delete_upload(storage_key)
        raise
    session.refresh(resource)
    return _resource_response(resource)


@router.get(
    "/workout-resources/{resource_id}/download",
    operation_id="downloadWorkoutResource",
)
def download_workout_resource(
    resource_id: UUID,
    _staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> FileResponse:
    resource = session.get(WorkoutResource, resource_id)
    if resource is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Workout resource not found", "code": "workout_resource_not_found"},
        )
    path = upload_path(resource.storage_key)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"error": "Workout resource is no longer available", "code": "workout_resource_missing"},
        )
    return FileResponse(
        path,
        media_type=resource.media_type,
        filename=resource.original_filename,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
