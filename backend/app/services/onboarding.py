from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.models.member import Member
from backend.app.models.member_onboarding import MemberOnboardingToken


ONBOARDING_TOKEN_LIFETIME = timedelta(days=14)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_member_onboarding_token(session: Session, member: Member) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    session.execute(
        update(MemberOnboardingToken)
        .where(
            MemberOnboardingToken.member_id == member.id,
            MemberOnboardingToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    expires_at = now + ONBOARDING_TOKEN_LIFETIME
    session.add(
        MemberOnboardingToken(
            member_id=member.id,
            token_hash=token_digest(token),
            expires_at=expires_at,
        )
    )
    return token, expires_at


def revoke_member_onboarding_tokens(session: Session, member_id: uuid.UUID) -> bool:
    result = session.execute(
        update(MemberOnboardingToken)
        .where(
            MemberOnboardingToken.member_id == member_id,
            MemberOnboardingToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return bool(result.rowcount)


def find_active_onboarding_token(
    session: Session, token: str
) -> MemberOnboardingToken | None:
    record = session.scalar(
        select(MemberOnboardingToken).where(
            MemberOnboardingToken.token_hash == token_digest(token),
            MemberOnboardingToken.revoked_at.is_(None),
        )
    )
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return record
