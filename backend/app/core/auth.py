from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import AppSettings, get_settings
from backend.app.db.session import get_db
from backend.app.models.member import Member, MemberStatus
from backend.app.models.staff_user import StaffRole, StaffStatus, StaffUser
from backend.app.services.clerk import get_verified_clerk_profile


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
        party = authorized_party.rstrip("/")
        if (
            party != origin
            and party not in settings.allowed_clerk_authorized_parties()
        ):
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


def get_member_db(
    claims: dict[str, Any] = Depends(get_clerk_claims),
    settings: AppSettings = Depends(get_settings),
) -> Generator[Session, None, None]:
    """Open the one server-configured gym database for member-only routes."""
    if not claims.get("sub"):
        raise HTTPException(
            status_code=401,
            detail={"error": "Sign in to continue", "code": "authentication_required"},
        )
    from backend.app.db.tenant_sessions import resolve_member_session

    session = resolve_member_session(settings.member_portal_gym_id)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_member(
    claims: dict[str, Any] = Depends(get_clerk_claims),
    session: Session = Depends(get_member_db),
    settings: AppSettings = Depends(get_settings),
) -> Member:
    """Resolve a Clerk session to one pre-registered member account.

    On first sign-in, only a verified Clerk email that matches exactly one
    staff-created member record can claim that record. The Clerk subject is
    then stored so subsequent requests do not depend on a mutable email.
    """
    clerk_user_id = claims.get("sub")
    if not isinstance(clerk_user_id, str) or not clerk_user_id:
        raise HTTPException(
            status_code=401,
            detail={"error": "Sign in to continue", "code": "authentication_required"},
        )

    member = session.scalar(
        select(Member).where(Member.clerk_user_id == clerk_user_id)
    )
    if member is None:
        if not settings.clerk_secret_key:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "Member account verification is not configured",
                    "code": "member_verification_not_configured",
                },
            )

        _, verified_emails = get_verified_clerk_profile(
            clerk_user_id, settings.clerk_secret_key
        )
        if not verified_emails:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Ask reception to match your verified sign-in email to your member record",
                    "code": "member_account_unlinked",
                },
            )

        matches = list(
            session.scalars(
                select(Member)
                .where(func.lower(Member.email).in_(verified_emails))
                .order_by(Member.id)
                .limit(2)
                .with_for_update()
            )
        )
        if len(matches) != 1:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Ask reception to match your verified sign-in email to one member record",
                    "code": "member_account_unlinked",
                },
            )

        member = matches[0]
        if (
            member.status != MemberStatus.ACTIVE.value
            or (member.clerk_user_id and member.clerk_user_id != clerk_user_id)
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "This member account is unavailable",
                    "code": "member_access_unavailable",
                },
            )
        member.clerk_user_id = clerk_user_id
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            member = session.scalar(
                select(Member).where(Member.clerk_user_id == clerk_user_id)
            )
            if member is None:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "This member account could not be linked",
                        "code": "member_account_unlinked",
                    },
                ) from None
        else:
            session.refresh(member)

    if member.status != MemberStatus.ACTIVE.value:
        raise HTTPException(
            status_code=403,
            detail={"error": "This member account is inactive", "code": "member_inactive"},
        )
    return member


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


def require_owner_or_receptionist(
    staff: StaffUser = Depends(get_current_staff),
) -> StaffUser:
    if staff.role not in {StaffRole.OWNER, StaffRole.RECEPTIONIST}:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Owner or receptionist access is required",
                "code": "operations_access_required",
            },
        )
    return staff


def require_owner_or_trainer(
    staff: StaffUser = Depends(get_current_staff),
) -> StaffUser:
    if staff.role not in {StaffRole.OWNER, StaffRole.TRAINER}:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Owner or trainer access is required",
                "code": "training_access_required",
            },
        )
    return staff


def require_fitness_staff(
    staff: StaffUser = Depends(get_current_staff),
) -> StaffUser:
    if staff.role not in {
        StaffRole.OWNER,
        StaffRole.RECEPTIONIST,
        StaffRole.TRAINER,
    }:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Staff access is required for fitness records",
                "code": "fitness_access_required",
            },
        )
    return staff
