from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
import re

from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings


def _database_url() -> str:
    value = get_settings().database_url
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    return value


@lru_cache
def get_engine() -> Engine:
    try:
        return create_engine(_database_url(), pool_pre_ping=True)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail={"error": "Database is not configured", "code": "database_unavailable"},
        ) from error


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    try:
        from backend.app.db.tenant_sessions import resolve_tenant_session, resolve_public_tenant_session
        is_public_link = re.fullmatch(r"/api/public/(?:onboarding/[^/]+|workout/[^/]+(?:/pdf)?)", request.url.path)
        session = resolve_public_tenant_session(request) if is_public_link else resolve_tenant_session(request)
    except HTTPException:
        raise

    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
