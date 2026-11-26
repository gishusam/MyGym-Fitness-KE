"""Resolve verified tenant session for MyGym operational APIs.

A browser-selected tenant is only a hint. Token signature and tenant staff membership
are checked on every tenant-routed request. No arbitrary database URL is accepted.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

_TENANT_NAME = re.compile(r"^mygym_tenant_[a-z0-9_]{3,48}$")


@lru_cache(maxsize=40)
def tenant_factory(name: str):
    if not _TENANT_NAME.fullmatch(name) or len(name) > 63:
        raise HTTPException(403, detail={"code":"tenant_unavailable", "error":"Invalid gym database"})
    template = os.environ.get("GYM_PROVISION_TENANT_URL", "")
    platform = os.environ.get("PLATFORM_DATABASE_URL", "")
    if not template or not platform:
        raise HTTPException(503, detail={"code":"tenant_configuration_missing", "error":"Tenant routing is not configured"})
    url = make_url(template)
    platform_url = make_url(platform)
    if url.get_backend_name() != "postgresql" or url.host != platform_url.host or url.port != platform_url.port or name == platform_url.database:
        raise HTTPException(503, detail={"code":"tenant_configuration_invalid", "error":"Tenant database configuration is invalid"})
    return sessionmaker(bind=create_engine(url.set(database=name).render_as_string(hide_password=False), pool_pre_ping=True), autoflush=False, expire_on_commit=False)


def resolve_tenant_session(request: Request) -> Session | None:
    tenant_id = request.cookies.get("mygym_gym")
    if not tenant_id:
        return None
    from backend.app.config import get_settings
    from backend.app.core.auth import get_clerk_claims
    from backend.app.models.staff_user import StaffUser, StaffStatus
    from backend.platform.app import GymTenant, platform_session_factory
    try:
        claims = get_clerk_claims(request, get_settings())
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(401, detail={"code":"authentication_required", "error":"Sign in to continue"})
        with platform_session_factory()() as db:
            gym = db.get(GymTenant, tenant_id)
            if gym is None or gym.status != "active" or gym.environment_kind != "customer" or not gym.database_ref:
                raise HTTPException(403, detail={"code":"gym_not_active", "error":"Gym is not available"})
            database_name = gym.database_ref
        session = tenant_factory(database_name)()
        try:
            staff = session.scalar(select(StaffUser).where(StaffUser.clerk_user_id == user_id))
            if staff is None or staff.status != StaffStatus.ACTIVE.value:
                raise HTTPException(403, detail={"code":"gym_access_denied", "error":"You do not have access to this gym"})
            return session
        except BaseException:
            session.close()
            raise
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail={"code":"gym_connection_unavailable", "error":"Unable to connect to the selected gym"}) from None
