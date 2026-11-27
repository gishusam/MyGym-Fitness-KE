"""Select tenant sessions only after Clerk authentication and active gym membership.

The cookie is an untrusted selection hint; the verified identity and staff record
in the registered tenant database authorize access. No default gym fallback.
"""
from __future__ import annotations

import os
import re
from uuid import UUID
from functools import lru_cache

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

_TENANT_NAME = re.compile(r"^mygym_tenant_[a-z0-9_]{3,48}$")
_EXISTING = {"development": "mygym_fitness_dev", "demo": "mygym_demo"}


def _reject(code: str, message: str) -> None:
    raise HTTPException(403, detail={"code": code, "error": message})


@lru_cache(maxsize=40)
def tenant_factory(name: str):
    if not _TENANT_NAME.fullmatch(name) or len(name) > 63:
        _reject("tenant_unavailable", "Invalid gym database")
    template = os.environ.get("GYM_PROVISION_TENANT_URL", "")
    platform = os.environ.get("PLATFORM_DATABASE_URL", "")
    if not template or not platform:
        raise HTTPException(503, detail={"code": "tenant_configuration_missing", "error": "Tenant routing is not configured"})
    url, platform_url = make_url(template), make_url(platform)
    if (url.get_backend_name() != "postgresql" or url.host != platform_url.host
            or url.port != platform_url.port or name == platform_url.database):
        raise HTTPException(503, detail={"code": "tenant_configuration_invalid", "error": "Tenant database configuration is invalid"})
    return sessionmaker(bind=create_engine(url.set(database=name).render_as_string(hide_password=False), pool_pre_ping=True),
                        autoflush=False, expire_on_commit=False)


@lru_cache(maxsize=2)
def existing_factory(name: str):
    """Only the two operator-linked legacy databases are allowed here."""
    if name not in _EXISTING.values():
        _reject("tenant_unavailable", "Unknown existing gym")
    source = os.environ.get("GYM_SOURCE_DATABASE_URL", "")
    platform = os.environ.get("PLATFORM_DATABASE_URL", "")
    if not source or not platform:
        raise HTTPException(503, detail={"code": "tenant_configuration_missing", "error": "Existing gym routing is not configured"})
    url, platform_url = make_url(source), make_url(platform)
    if (url.get_backend_name() != "postgresql" or platform_url.get_backend_name() != "postgresql"
            or url.database != "mygym_fitness_dev" or platform_url.database != "mygym_platform"
            or (url.host, url.port) != (platform_url.host, platform_url.port)):
        raise HTTPException(503, detail={"code": "tenant_configuration_invalid", "error": "Existing gym routing is not configured safely"})
    return sessionmaker(bind=create_engine(url.set(database=name).render_as_string(hide_password=False), pool_pre_ping=True),
                        autoflush=False, expire_on_commit=False)


def resolve_tenant_session(request: Request) -> Session:
    """Require authenticated, active staff membership in the selected gym.

    A browser may suggest a gym in its cookie, but no URL/header/body/DB URL
    overrides registered mapping or staff membership from the verified token.
    """
    tenant_id = request.cookies.get("mygym_gym")
    if not tenant_id:
        _reject("gym_selection_required", "Select your gym before accessing its records")

    from backend.app.config import get_settings
    from backend.app.core.auth import get_clerk_claims
    from backend.app.models.staff_user import StaffStatus, StaffUser
    from backend.platform.app import GymTenant, platform_session_factory

    claims = get_clerk_claims(request, get_settings())
    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(401, detail={"code": "authentication_required", "error": "Sign in to continue"})

    # Platform-only identities may not use normal gym-data APIs, even when
    # a stale gym staff row exists for the same Clerk subject.
    admins = {s.strip() for s in os.environ.get("PLATFORM_ADMIN_CLERK_IDS", "").split(",") if s.strip()}
    if user_id in admins:
        _reject("platform_admin_separate", "Platform administrators cannot access gym records through this API")

    try:
        with platform_session_factory()() as registry:
            gym = registry.get(GymTenant, tenant_id)
            if gym is None or gym.status != "active" or not gym.database_ref:
                _reject("gym_access_denied", "This gym is not available")
            database_name = gym.database_ref
            if gym.environment_kind == "customer":
                factory = tenant_factory(database_name)
            elif gym.environment_kind in _EXISTING and database_name == _EXISTING[gym.environment_kind]:
                factory = existing_factory(database_name)
            else:
                _reject("gym_access_denied", "Unrecognized gym database mapping")

        session = factory()
        try:
            staff = session.scalar(select(StaffUser).where(StaffUser.clerk_user_id == user_id))
            if staff is None or staff.status != StaffStatus.ACTIVE.value:
                _reject("gym_access_denied", "You do not have access to this gym")
            session.info["gym_id"] = tenant_id
            return session
        except BaseException:
            session.close()
            raise
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail={"code": "gym_connection_unavailable", "error": "Unable to connect to the selected gym"}) from None



def resolve_public_tenant_session(request: Request) -> Session:
    """Resolve one registered active gym for a public bearer-token link.

    The query gym UUID is an untrusted routing hint. Authorization happens
    when the public endpoint validates the opaque token in that one database.
    Never scan other tenants or fall back to the development database.
    """
    gym_id = request.query_params.get("gym", "")
    try:
        if str(UUID(gym_id)) != gym_id:
            raise ValueError("noncanonical gym ID")
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(404, detail={"code": "public_link_unavailable", "error": "Link unavailable"}) from None

    from backend.platform.app import GymTenant, platform_session_factory
    try:
        with platform_session_factory()() as registry:
            gym = registry.get(GymTenant, gym_id)
            if gym is None or gym.status != "active" or not gym.database_ref:
                raise HTTPException(404, detail={"code": "public_link_unavailable", "error": "Link unavailable"})
            if gym.environment_kind == "customer":
                factory = tenant_factory(gym.database_ref)
            elif gym.environment_kind in _EXISTING and gym.database_ref == _EXISTING[gym.environment_kind]:
                factory = existing_factory(gym.database_ref)
            else:
                raise HTTPException(404, detail={"code": "public_link_unavailable", "error": "Link unavailable"})
        session = factory()
        session.info["gym_id"] = gym_id
        return session
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail={"code": "gym_connection_unavailable", "error": "Link temporarily unavailable"}) from None
