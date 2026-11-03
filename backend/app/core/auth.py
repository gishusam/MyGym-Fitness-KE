from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import AppSettings, get_settings
from backend.app.db.session import get_db
from backend.app.models.staff_user import StaffRole, StaffStatus, StaffUser


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_jwk_set=True, lifespan=3600)


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")

    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    host = forwarded_host or request.headers.get("host")
    if not host:
        return None

    forwarded_proto = request.headers.get(
        "x-forwarded-proto", request.url.scheme
    ).split(",", 1)[0].strip()
    return f"{forwarded_proto}://{host}".rstrip("/")


def get_clerk_claims(
    request: Request,
    settings: AppSettings = Depends(get_settings),
) -> dict[str, Any]:
    token = request.cookies.get("__session")
    if not token:
        authorization = request.headers.get("authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "Sign in to continue", "code": "authentication_required"},
        )

    try:
        issuer = settings.clerk_issuer()
        signing_key = _jwks_client(settings.clerk_jwks_url()).get_signing_key_from_jwt(
            token
        )
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except (PyJWKClientConnectionError, PyJWKClientError):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Sign-in verification is temporarily unavailable",
                "code": "auth_verification_unavailable",
            },
        ) from None
    except (jwt.PyJWTError, RuntimeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail={"error": "Your sign-in session is invalid or expired", "code": "invalid_session"},
        ) from None

    authorized_party = claims.get("azp")
    if authorized_party:
        origin = _request_origin(request)
        if not origin or authorized_party.rstrip("/") != origin:
            raise HTTPException(
                status_code=401,
                detail={"error": "Sign-in origin is not allowed", "code": "invalid_session_origin"},
            )

    if claims.get("sts") == "pending":
        raise HTTPException(
            status_code=403,
            detail={"error": "Complete account setup before continuing", "code": "account_setup_pending"},
        )

    return claims


def get_current_staff(
    claims: dict[str, Any] = Depends(get_clerk_claims),
    session: Session = Depends(get_db),
) -> StaffUser:
    clerk_user_id = claims.get("sub")
    staff = session.scalar(
        select(StaffUser).where(StaffUser.clerk_user_id == clerk_user_id)
    )
    if staff is None:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "This account has not been assigned a MyGym staff role",
                "code": "staff_access_pending",
            },
        )
    if staff.status != StaffStatus.ACTIVE:
        raise HTTPException(
            status_code=403,
            detail={"error": "This staff account is inactive", "code": "staff_inactive"},
        )
    return staff


def require_owner(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
    if staff.role != StaffRole.OWNER:
        raise HTTPException(
            status_code=403,
            detail={"error": "Owner access is required", "code": "owner_access_required"},
        )
    return staff
