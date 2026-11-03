from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.auth import get_clerk_claims, get_current_staff
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.gym_settings import GymSettings
from backend.app.models.staff_user import StaffRole, StaffUser
from backend.app.schemas.staff import CurrentStaff
from backend.app.services.clerk import get_verified_clerk_profile

router = APIRouter(prefix="/staff", tags=["staff"])


@router.get("/me", operation_id="getCurrentStaff", response_model=CurrentStaff)
def current_staff(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
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
