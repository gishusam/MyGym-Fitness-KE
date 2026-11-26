"""Verified, idempotent gym registration with opt-in automatic provisioning.

Trusted platform service alone holds CREATE DATABASE credentials. No client can
submit a database URL or choose a database role. Running in-process is suitable
for a local single-process pilot; production should use a durable worker queue.
"""
from __future__ import annotations

import logging
import os
import re
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.core.auth import get_clerk_claims
from backend.app.services.clerk import get_verified_clerk_profile
from backend.platform.app import GymTenant, PlatformAudit, platform_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/platform/signup", tags=["gym-signup"])


class SignupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gym_name: str = Field(min_length=2, max_length=120)


class SignupView(BaseModel):
    id: str
    gym_name: str
    status: str
    auto_setup_available: bool = False


def auto_setup_available() -> bool:
    """Operator opt-in and required server-only secrets (never returned)."""
    needed = (
        "CLERK_SECRET_KEY", "PLATFORM_DATABASE_URL", "GYM_PROVISION_ADMIN_URL",
        "GYM_PROVISION_TENANT_URL", "GYM_PROVISION_OWNER_ROLE",
    )
    return os.getenv("MYGYM_AUTO_PROVISION_ENABLED") == "1" and all(os.getenv(k) for k in needed)


def _owner_id(claims: dict) -> str:
    sub = claims.get("sub", "")
    if not isinstance(sub, str) or not sub.startswith("user_"):
        raise HTTPException(401, detail={"code": "authentication_required", "error": "Sign in first"})
    return sub


def _record(gym: GymTenant) -> SignupView:
    return SignupView(id=gym.id, gym_name=gym.name, status=gym.status,
                      auto_setup_available=auto_setup_available())


def _owned(session: Session, owner_id: str) -> GymTenant | None:
    return session.scalar(
        select(GymTenant).where(
            GymTenant.owner_clerk_user_id == owner_id,
            GymTenant.environment_kind == "customer",
        ).order_by(GymTenant.created_at.desc()).limit(1)
    )


def _schedule(gym: GymTenant, background: BackgroundTasks) -> None:
    # Do not attempt provisioning without explicit operator configuration.
    if auto_setup_available() and gym.status in {
        "pending_provisioning", "provision_failed", "awaiting_owner", "provisioning"
    }:
        from backend.platform.auto_provision import run_auto_provision
        background.add_task(run_auto_provision, gym.id)


@router.get("/me", response_model=SignupView | None)
def get_my_signup(
    background: BackgroundTasks,
    claims: dict = Depends(get_clerk_claims),
    db: Session = Depends(platform_db),
):
    gym = _owned(db, _owner_id(claims))
    if gym is None:
        return None
    _schedule(gym, background)
    return _record(gym)


@router.post("/gyms", response_model=SignupView, status_code=201)
def signup_gym(
    data: SignupInput,
    background: BackgroundTasks,
    claims: dict = Depends(get_clerk_claims),
    db: Session = Depends(platform_db),
):
    owner_id = _owner_id(claims)
    existing = _owned(db, owner_id)
    if existing:
        _schedule(existing, background)
        return _record(existing)
    secret = get_settings().clerk_secret_key
    if not secret:
        raise HTTPException(503, detail={"code": "signup_unavailable", "error": "Account verification unavailable"})
    _, verified_emails = get_verified_clerk_profile(owner_id, secret)
    if not verified_emails:
        raise HTTPException(403, detail={"code": "email_not_verified", "error": "Verify your email before creating a gym"})
    name = " ".join(data.gym_name.split())
    if len(name) < 2:
        raise HTTPException(422, detail={"code": "gym_name_invalid", "error": "Enter the gym name"})
    stem = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:34].strip("-") or "gym"
    gym = GymTenant(name=name, slug=f"{stem}-{secrets.token_hex(4)}",
                    owner_clerk_user_id=owner_id, environment_kind="customer",
                    status="pending_provisioning")
    db.add(gym)
    try:
        db.flush()
        db.add(PlatformAudit(actor_clerk_user_id=owner_id, gym_id=gym.id,
                             event="customer_signup_requested"))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _owned(db, owner_id)
        if existing:
            _schedule(existing, background)
            return _record(existing)
        raise HTTPException(409, detail={"code": "signup_conflict", "error": "Please retry gym registration"}) from None
    _schedule(gym, background)
    logger.info("Gym signup queued for automatic setup: gym=%s", gym.id)
    return _record(gym)
