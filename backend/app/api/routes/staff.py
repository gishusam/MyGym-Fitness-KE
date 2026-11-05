from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.auth import get_clerk_claims, get_current_staff, require_owner
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.gym_settings import GymSettings
from backend.app.models.staff_user import StaffRole, StaffStatus, StaffUser
from backend.app.schemas.staff import CurrentStaff
from backend.app.schemas.workspaces import StaffCreateInput, StaffMember, StaffUpdateInput
from backend.app.services.clerk import (
    find_verified_clerk_user_by_email,
    get_verified_clerk_profile,
)

router = APIRouter(prefix="/staff", tags=["staff"])


@router.get("/me", operation_id="getCurrentStaff", response_model=CurrentStaff)
def current_staff(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    return staff


@router.get("", operation_id="listStaff", response_model=list[StaffMember])
def list_staff(
    _owner: StaffUser = Depends(require_owner),
    session: Session = Depends(get_db),
) -> list[StaffUser]:
    return list(
        session.scalars(
            select(StaffUser).order_by(StaffUser.status, StaffUser.name, StaffUser.id)
        )
    )


@router.post("", operation_id="createStaff", response_model=StaffMember, status_code=201)
def create_staff(
    data: StaffCreateInput,
    owner: StaffUser = Depends(require_owner),
    session: Session = Depends(get_db),
) -> StaffUser:
    if not get_settings().clerk_secret_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Staff account verification is not configured",
                "code": "staff_verification_not_configured",
            },
        )
    existing = session.scalar(
        select(StaffUser).where(func.lower(StaffUser.email) == data.email).limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "This person already has a staff role", "code": "staff_already_assigned"},
        )

    identity = find_verified_clerk_user_by_email(
        data.email, get_settings().clerk_secret_key
    )
    if identity is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "A verified sign-in account with this email must exist before assigning a gym role",
                "code": "verified_staff_account_not_found",
            },
        )

    user_id, name = identity
    staff = StaffUser(
        id=uuid.uuid4(),
        clerk_user_id=user_id,
        name=name,
        email=data.email,
        role=data.role,
        status=StaffStatus.ACTIVE.value,
    )
    session.add(staff)
    session.add(
        AuditLog(
            actor_staff_id=owner.id,
            action="staff.role_assigned",
            entity_type="staff_user",
            entity_id=str(staff.id),
            details={"role": data.role, "email": data.email},
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "This sign-in account already has a staff role", "code": "staff_already_assigned"},
        ) from None
    session.refresh(staff)
    return staff


@router.patch(
    "/{staff_id}", operation_id="updateStaff", response_model=StaffMember
)
def update_staff(
    staff_id: uuid.UUID,
    changes: StaffUpdateInput,
    owner: StaffUser = Depends(require_owner),
    session: Session = Depends(get_db),
) -> StaffUser:
    staff = session.scalar(
        select(StaffUser).where(StaffUser.id == staff_id).with_for_update()
    )
    if staff is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Staff member not found", "code": "staff_not_found"},
        )

    updates = changes.model_dump(exclude_unset=True)
    if any(value is None for value in updates.values()):
        raise HTTPException(
            status_code=422,
            detail={"error": "Staff role and status cannot be cleared", "code": "invalid_staff_update"},
        )
    next_role = updates.get("role", staff.role)
    next_status = updates.get("status", staff.status)
    if staff.role == StaffRole.OWNER.value and (
        next_role != StaffRole.OWNER.value or next_status != StaffStatus.ACTIVE.value
    ):
        active_owners = session.scalar(
            select(func.count())
            .select_from(StaffUser)
            .where(
                StaffUser.role == StaffRole.OWNER.value,
                StaffUser.status == StaffStatus.ACTIVE.value,
            )
        ) or 0
        if active_owners <= 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "The gym must keep at least one active owner",
                    "code": "last_active_owner",
                },
            )

    previous = {"role": staff.role, "status": staff.status}
    for field, value in updates.items():
        setattr(staff, field, value)
    session.add(
        AuditLog(
            actor_staff_id=owner.id,
            action="staff.role_or_status_updated",
            entity_type="staff_user",
            entity_id=str(staff.id),
            details={"before": previous, "after": {"role": staff.role, "status": staff.status}},
        )
    )
    session.commit()
    session.refresh(staff)
    return staff


@router.post(
    "/bootstrap-owner",
    operation_id="bootstrapInitialOwner",
    response_model=CurrentStaff,
)
def bootstrap_initial_owner(
    claims: dict = Depends(get_clerk_claims),
    session: Session = Depends(get_db),
) -> StaffUser:
    config = get_settings()
    allowed_email = (config.initial_owner_email or "").strip().casefold()
    if not allowed_email:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Initial owner email is not configured",
                "code": "owner_bootstrap_not_configured",
            },
        )
    if not config.clerk_secret_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Staff account verification is not configured",
                "code": "owner_bootstrap_not_configured",
            },
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"error": "Sign in to continue", "code": "authentication_required"},
        )

    name, verified_emails = get_verified_clerk_profile(
        user_id, config.clerk_secret_key
    )
    if allowed_email not in verified_emails:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "This verified email is not the configured first owner",
                "code": "owner_bootstrap_forbidden",
            },
        )
    verified_email = allowed_email

    settings = session.scalar(
        select(GymSettings).where(GymSettings.id == 1).with_for_update()
    )
    if settings is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Gym settings are not initialized",
                "code": "foundation_not_initialized",
            },
        )
    if settings.owner_bootstrap_completed or session.scalar(
        select(StaffUser.id).limit(1)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "The first owner account has already been set up",
                "code": "owner_bootstrap_complete",
            },
        )

    owner = StaffUser(
        id=uuid.uuid4(),
        clerk_user_id=user_id,
        name=name or allowed_email.split("@", 1)[0],
        email=verified_email,
        role=StaffRole.OWNER,
    )
    session.add(owner)
    session.flush()
    settings.owner_bootstrap_completed = True
    settings.updated_by = owner.id
    session.add(
        AuditLog(
            actor_staff_id=owner.id,
            action="staff.owner_bootstrapped",
            entity_type="staff_user",
            entity_id=str(owner.id),
            details={"role": StaffRole.OWNER.value},
        )
    )
    session.commit()
    session.refresh(owner)
    return owner
