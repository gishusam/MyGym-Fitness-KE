from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import get_current_staff, require_owner_or_trainer
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.gym_event import EventRegistration, GymEvent
from backend.app.models.member import Member, MemberStatus
from backend.app.models.staff_user import StaffRole, StaffStatus, StaffUser
from backend.app.schemas.workspaces import (
    EventInput,
    EventRegistrationInput,
    EventRegistrationResponse,
    EventResponse,
    EventUpdate,
)
from backend.app.services.operations import get_gym_timezone, gym_now
from backend.app.services.private_uploads import (
    delete_upload,
    save_request_upload,
    upload_path,
)

router = APIRouter(prefix="/events", tags=["events"])


def _local_utc(value: datetime, session: Session) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_gym_timezone(session))
    return value.astimezone(timezone.utc)


def _stored_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_response(
    session: Session,
    event: GymEvent,
    instructor_name: str | None = None,
) -> EventResponse:
    registered = event.confirmed_count
    return EventResponse(
        id=event.id,
        name=event.name,
        description=event.description,
        starts_at=_stored_utc(event.starts_at),
        ends_at=_stored_utc(event.ends_at),
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


def _find_event(session: Session, event_id: UUID, *, lock: bool = False) -> GymEvent:
    stmt = select(GymEvent).where(GymEvent.id == event_id)
    if lock:
        stmt = stmt.with_for_update()
    event = session.scalar(stmt)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Event not found", "code": "event_not_found"},
        )
    return event


def _validate_instructor(session: Session, instructor_id: UUID | None) -> None:
    if instructor_id is None:
        return
    instructor = session.get(StaffUser, instructor_id)
    if (
        instructor is None
        or instructor.status != StaffStatus.ACTIVE.value
        or instructor.role not in {StaffRole.OWNER.value, StaffRole.TRAINER.value}
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Choose an active owner or trainer as the instructor",
                "code": "invalid_event_instructor",
            },
        )


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


def _registration_response(
    registration: EventRegistration, member: Member
) -> EventRegistrationResponse:
    return EventRegistrationResponse(
        id=registration.id,
        event_id=registration.event_id,
        member_id=member.id,
        member_number=member.member_number,
        member_name=member.full_name,
        status=registration.status,
        registered_at=registration.registered_at,
    )


@router.get("", operation_id="listEvents", response_model=list[EventResponse])
def list_events(
    timeframe: Literal["upcoming", "past"] | None = None,
    status: Literal["draft", "published", "cancelled"] | None = None,
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> list[EventResponse]:
    now = _local_utc(gym_now(session), session)
    stmt = (
        select(GymEvent, StaffUser.name)
        .outerjoin(StaffUser, GymEvent.instructor_staff_id == StaffUser.id)
    )
    if staff.role == StaffRole.RECEPTIONIST.value:
        stmt = stmt.where(GymEvent.status == "published")
    elif status is not None:
        stmt = stmt.where(GymEvent.status == status)
    if timeframe == "upcoming":
        stmt = stmt.where(GymEvent.ends_at >= now)
    elif timeframe == "past":
        stmt = stmt.where(GymEvent.ends_at < now)
    rows = session.execute(
        stmt.order_by(GymEvent.starts_at.desc() if timeframe == "past" else GymEvent.starts_at)
        .limit(200)
    ).all()
    return [
        _event_response(session, event, instructor_name)
        for event, instructor_name in rows
    ]


@router.get(
    "/instructors",
    operation_id="listEventInstructors",
    response_model=list[dict],
)
def list_event_instructors(
    _staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> list[dict]:
    staff = session.scalars(
        select(StaffUser)
        .where(
            StaffUser.status == StaffStatus.ACTIVE.value,
            StaffUser.role.in_((StaffRole.OWNER.value, StaffRole.TRAINER.value)),
        )
        .order_by(StaffUser.name, StaffUser.id)
    )
    return [{"id": person.id, "name": person.name, "role": person.role} for person in staff]


@router.get(
    "/{event_id}",
    operation_id="getEvent",
    response_model=EventResponse,
)
def get_event(
    event_id: UUID,
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> EventResponse:
    event = _find_event(session, event_id)
    if staff.role == StaffRole.RECEPTIONIST.value and event.status != "published":
        raise HTTPException(
            status_code=404,
            detail={"error": "Event not found", "code": "event_not_found"},
        )
    instructor = session.get(StaffUser, event.instructor_staff_id) if event.instructor_staff_id else None
    return _event_response(session, event, instructor.name if instructor else None)


@router.post("", operation_id="createEvent", response_model=EventResponse, status_code=201)
def create_event(
    data: EventInput,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> EventResponse:
    _validate_instructor(session, data.instructor_staff_id)
    starts_at = _local_utc(data.starts_at, session)
    ends_at = _local_utc(data.ends_at, session)
    if ends_at <= starts_at:
        raise HTTPException(
            status_code=422,
            detail={"error": "Event end must be later than its start", "code": "invalid_event_period"},
        )
    event = GymEvent(
        id=uuid4(),
        name=data.name,
        description=data.description,
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=data.capacity,
        instructor_staff_id=data.instructor_staff_id,
        status=data.status,
        created_by_staff_id=staff.id,
    )
    session.add(event)
    session.flush()
    _audit(
        session,
        staff,
        "event.created",
        "gym_event",
        event.id,
        {"status": event.status, "capacity": event.capacity},
    )
    session.commit()
    session.refresh(event)
    instructor = session.get(StaffUser, event.instructor_staff_id) if event.instructor_staff_id else None
    return _event_response(session, event, instructor.name if instructor else None)


@router.patch(
    "/{event_id}",
    operation_id="updateEvent",
    response_model=EventResponse,
)
def update_event(
    event_id: UUID,
    changes: EventUpdate,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> EventResponse:
    event = _find_event(session, event_id, lock=True)
    updates = changes.model_dump(exclude_unset=True)
    if any(value is None for key, value in updates.items() if key != "description" and key != "instructor_staff_id"):
        raise HTTPException(
            status_code=422,
            detail={"error": "Event name, status, time and capacity cannot be cleared", "code": "invalid_event_update"},
        )
    if "instructor_staff_id" in changes.model_fields_set:
        _validate_instructor(session, changes.instructor_staff_id)

    starts_at = (
        _local_utc(changes.starts_at, session)
        if "starts_at" in changes.model_fields_set
        else _stored_utc(event.starts_at)
    )
    ends_at = (
        _local_utc(changes.ends_at, session)
        if "ends_at" in changes.model_fields_set
        else _stored_utc(event.ends_at)
    )
    if ends_at <= starts_at:
        raise HTTPException(
            status_code=422,
            detail={"error": "Event end must be later than its start", "code": "invalid_event_period"},
        )
    next_capacity = updates.get("capacity", event.capacity)
    registered_count = event.confirmed_count
    if next_capacity < registered_count:
        raise HTTPException(
            status_code=409,
            detail={"error": "Capacity cannot be lower than confirmed registrations", "code": "event_capacity_below_bookings"},
        )
    if "starts_at" in changes.model_fields_set:
        event.starts_at = starts_at
    if "ends_at" in changes.model_fields_set:
        event.ends_at = ends_at
    for field, value in updates.items():
        if field not in {"starts_at", "ends_at"}:
            setattr(event, field, value)
    _audit(
        session,
        staff,
        "event.updated",
        "gym_event",
        event.id,
        {"fields": sorted(changes.model_fields_set)},
    )
    session.commit()
    session.refresh(event)
    instructor = session.get(StaffUser, event.instructor_staff_id) if event.instructor_staff_id else None
    return _event_response(session, event, instructor.name if instructor else None)


@router.post(
    "/{event_id}/registrations",
    operation_id="registerMemberForEvent",
    response_model=EventRegistrationResponse,
    status_code=201,
)
def register_member_for_event(
    event_id: UUID,
    data: EventRegistrationInput,
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> EventRegistrationResponse:
    now = datetime.now(timezone.utc)
    # Reserve the slot with a conditional UPDATE before reading event or member
    # rows. The event row is locked atomically by both PostgreSQL and SQLite, so
    # simultaneous requests cannot both consume the final place.
    reservation = session.execute(
        update(GymEvent)
        .where(
            GymEvent.id == event_id,
            GymEvent.status == "published",
            GymEvent.ends_at >= now,
            GymEvent.confirmed_count < GymEvent.capacity,
            ~select(EventRegistration.id).where(
                EventRegistration.event_id == event_id,
                EventRegistration.member_id == data.member_id,
                EventRegistration.status == "confirmed",
            ).exists(),
        )
        .values(confirmed_count=GymEvent.confirmed_count + 1)
    )
    if reservation.rowcount != 1:
        session.rollback()
        event = _find_event(session, event_id)
        if event.status != "published" or _stored_utc(event.ends_at) < now:
            raise HTTPException(
                status_code=409,
                detail={"error": "This event is not open for registration", "code": "event_not_open"},
            )
        duplicate = session.scalar(
            select(EventRegistration.id).where(
                EventRegistration.event_id == event_id,
                EventRegistration.member_id == data.member_id,
                EventRegistration.status == "confirmed",
            )
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail={"error": "This member is already registered", "code": "event_duplicate_registration"},
            )
        raise HTTPException(
            status_code=409,
            detail={"error": "This event has reached capacity", "code": "event_capacity_reached"},
        )
    event = _find_event(session, event_id)
    member = session.get(Member, data.member_id)
    if member is None or member.status != MemberStatus.ACTIVE.value:
        session.rollback()
        raise HTTPException(
            status_code=404,
            detail={"error": "Active member not found", "code": "member_not_found"},
        )
    existing = session.scalar(
        select(EventRegistration)
        .where(
            EventRegistration.event_id == event.id,
            EventRegistration.member_id == member.id,
        )
        .with_for_update()
    )
    if existing is not None and existing.status == "confirmed":
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "This member is already registered", "code": "event_duplicate_registration"},
        )

    if existing is None:
        registration = EventRegistration(
            id=uuid4(),
            event_id=event.id,
            member_id=member.id,
            registered_by_staff_id=staff.id,
            status="confirmed",
        )
        session.add(registration)
    else:
        registration = existing
        registration.status = "confirmed"
        registration.registered_by_staff_id = staff.id
        registration.registered_at = now
    _audit(
        session,
        staff,
        "event.member_registered",
        "event_registration",
        registration.id,
        {"event_id": str(event.id), "member_id": str(member.id)},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "This member is already registered", "code": "event_duplicate_registration"},
        ) from None
    session.refresh(registration)
    return _registration_response(registration, member)


@router.get(
    "/{event_id}/registrations",
    operation_id="listEventRegistrations",
    response_model=list[EventRegistrationResponse],
)
def list_event_registrations(
    event_id: UUID,
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> list[EventRegistrationResponse]:
    event = _find_event(session, event_id)
    if staff.role == StaffRole.RECEPTIONIST.value and event.status != "published":
        raise HTTPException(status_code=404, detail={"error": "Event not found", "code": "event_not_found"})
    rows = session.execute(
        select(EventRegistration, Member)
        .join(Member, EventRegistration.member_id == Member.id)
        .where(EventRegistration.event_id == event.id)
        .order_by(EventRegistration.registered_at.desc(), Member.full_name)
    ).all()
    return [_registration_response(registration, member) for registration, member in rows]


@router.delete(
    "/{event_id}/registrations/{registration_id}",
    operation_id="cancelEventRegistration",
    response_model=EventRegistrationResponse,
)
def cancel_event_registration(
    event_id: UUID,
    registration_id: UUID,
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> EventRegistrationResponse:
    event = _find_event(session, event_id, lock=True)
    if staff.role == StaffRole.RECEPTIONIST.value and event.status != "published":
        raise HTTPException(
            status_code=404,
            detail={"error": "Event not found", "code": "event_not_found"},
        )
    registration = session.scalar(
        select(EventRegistration)
        .where(
            EventRegistration.id == registration_id,
            EventRegistration.event_id == event_id,
        )
        .with_for_update()
    )
    if registration is None or registration.status == "cancelled":
        raise HTTPException(
            status_code=404,
            detail={"error": "Active event registration not found", "code": "event_registration_not_found"},
        )
    member = session.get(Member, registration.member_id)
    registration.status = "cancelled"
    event.confirmed_count = max(event.confirmed_count - 1, 0)
    _audit(
        session,
        staff,
        "event.registration_cancelled",
        "event_registration",
        registration.id,
        {"event_id": str(event_id)},
    )
    session.commit()
    session.refresh(registration)
    return _registration_response(registration, member)


@router.post(
    "/{event_id}/cover",
    operation_id="uploadEventCover",
    response_model=EventResponse,
)
async def upload_event_cover(
    event_id: UUID,
    request: Request,
    staff: StaffUser = Depends(require_owner_or_trainer),
    session: Session = Depends(get_db),
) -> EventResponse:
    event = _find_event(session, event_id, lock=True)
    storage_key, filename, media_type, size = await save_request_upload(
        request, images_only=True
    )
    previous_key = event.cover_storage_key
    event.cover_storage_key = storage_key
    event.cover_filename = filename
    event.cover_media_type = media_type
    event.cover_size_bytes = size
    _audit(
        session,
        staff,
        "event.cover_uploaded",
        "gym_event",
        event.id,
        {"media_type": media_type, "size_bytes": size},
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        delete_upload(storage_key)
        raise
    session.refresh(event)
    delete_upload(previous_key)
    instructor = session.get(StaffUser, event.instructor_staff_id) if event.instructor_staff_id else None
    return _event_response(session, event, instructor.name if instructor else None)


@router.get("/{event_id}/cover", operation_id="downloadEventCover")
def download_event_cover(
    event_id: UUID,
    staff: StaffUser = Depends(get_current_staff),
    session: Session = Depends(get_db),
) -> FileResponse:
    event = _find_event(session, event_id)
    if staff.role == StaffRole.RECEPTIONIST.value and event.status != "published":
        raise HTTPException(status_code=404, detail={"error": "Event not found", "code": "event_not_found"})
    if not event.cover_storage_key or not event.cover_filename:
        raise HTTPException(
            status_code=404,
            detail={"error": "Event cover not found", "code": "event_cover_not_found"},
        )
    path = upload_path(event.cover_storage_key)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"error": "Event cover is no longer available", "code": "event_cover_missing"},
        )
    return FileResponse(
        path,
        media_type=event.cover_media_type or "application/octet-stream",
        filename=event.cover_filename,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
