from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner, require_owner_or_receptionist
from backend.app.db.session import get_db
from backend.app.models.audit_log import AuditLog
from backend.app.models.gym_settings import GymSettings
from backend.app.models.staff_user import StaffUser
from backend.app.schemas.gym_settings import GymSettingsResponse, GymSettingsUpdate

router = APIRouter(prefix="/gym-settings", tags=["settings"])


def _get_settings(session: Session) -> GymSettings:
    settings = session.get(GymSettings, 1)
    if settings is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Gym settings are not initialized",
                "code": "foundation_not_initialized",
            },
        )
    return settings


@router.get("", operation_id="getGymSettings", response_model=GymSettingsResponse)
def read_gym_settings(
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> GymSettings:
    return _get_settings(session)


@router.patch("", operation_id="updateGymSettings", response_model=GymSettingsResponse)
def update_gym_settings(
    changes: GymSettingsUpdate,
    staff: StaffUser = Depends(require_owner),
    session: Session = Depends(get_db),
) -> GymSettings:
    settings = session.get(GymSettings, 1, with_for_update=True)
    if settings is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Gym settings are not initialized",
                "code": "foundation_not_initialized",
            },
        )

    updates = changes.model_dump(exclude_unset=True)
    before = {
        field: getattr(settings, field)
        for field in updates
    }
    for field, value in updates.items():
        setattr(settings, field, value)
    settings.updated_by = staff.id
    session.add(
        AuditLog(
            actor_staff_id=staff.id,
            action="gym_settings.updated",
            entity_type="gym_settings",
            entity_id="1",
            details={"changed_fields": sorted(updates), "previous_values": before},
        )
    )
    session.commit()
    session.refresh(settings)
    return settings
