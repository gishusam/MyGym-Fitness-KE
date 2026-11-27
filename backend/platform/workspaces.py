"""Find only gym workspaces in which the signed-in Clerk subject is active staff.

Every candidate comes from the server-side platform registry. Registry ownership
alone is NOT authorization; every result is checked against its own staff_users.
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.auth import get_clerk_claims
from backend.app.db.tenant_sessions import _EXISTING, existing_factory, tenant_factory
from backend.app.models.staff_user import StaffStatus, StaffUser
from backend.platform.app import GymTenant, platform_db

router = APIRouter(prefix="/api/platform/workspaces", tags=["workspaces"])


class WorkspaceView(BaseModel):
    id: str
    name: str
    role: str
    environment_kind: str


def available_workspaces(subject: str, registry: Session) -> list[WorkspaceView]:
    gyms = registry.scalars(select(GymTenant).where(GymTenant.status == "active").order_by(GymTenant.name)).all()
    results: list[WorkspaceView] = []
    for gym in gyms:
        if not gym.database_ref:
            continue
        if gym.environment_kind == "customer":
            factory = tenant_factory(gym.database_ref)
        elif gym.environment_kind in _EXISTING and gym.database_ref == _EXISTING[gym.environment_kind]:
            factory = existing_factory(gym.database_ref)
        else:
            # Never connect using an unrecognized registry mapping.
            continue
        try:
            with factory() as tenant:
                staff = tenant.scalar(select(StaffUser).where(StaffUser.clerk_user_id == subject))
                if staff is not None and staff.status == StaffStatus.ACTIVE.value:
                    results.append(WorkspaceView(id=gym.id, name=gym.name, role=staff.role,
                                                 environment_kind=gym.environment_kind))
        except HTTPException:
            raise
        except Exception:
            # An unavailable tenant must not be mistaken for "not a member".
            raise HTTPException(503, detail={"code": "workspace_lookup_unavailable",
                                             "error": "Unable to verify gym access"}) from None
    return results


@router.get("/me", response_model=list[WorkspaceView])
def my_workspaces(claims: dict = Depends(get_clerk_claims), registry: Session = Depends(platform_db)):
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(401, detail={"code": "authentication_required", "error": "Sign in to continue"})
    admins = {s.strip() for s in os.environ.get("PLATFORM_ADMIN_CLERK_IDS", "").split(",") if s.strip()}
    if subject in admins:
        return []
    return available_workspaces(subject, registry)
