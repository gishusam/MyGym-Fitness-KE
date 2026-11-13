"""Standalone MyGym platform-admin API. Does not connect to any gym database."""
from __future__ import annotations

import os
from collections.abc import Generator
from datetime import datetime, timezone
from functools import lru_cache
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.app.core.auth import get_clerk_claims


class PlatformBase(DeclarativeBase):
    pass


class GymTenant(PlatformBase):
    __tablename__ = "platform_gyms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_clerk_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_provisioning")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PlatformAudit(PlatformBase):
    __tablename__ = "platform_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_clerk_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gym_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("platform_gyms.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class GymCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    owner_clerk_user_id: str | None = Field(default=None, min_length=3, max_length=128)


class GymView(BaseModel):
    id: str
    slug: str
    name: str
    ownerClerkUserId: str | None
    status: str

    @classmethod
    def from_tenant(cls, tenant: GymTenant) -> "GymView":
        return cls(id=tenant.id, slug=tenant.slug, name=tenant.name,
                   ownerClerkUserId=tenant.owner_clerk_user_id, status=tenant.status)


def require_platform_admin(claims: dict = Depends(get_clerk_claims)) -> str:
    # Explicit Clerk user-ID allowlist, not email or a gym Owner role.
    allowed = {item.strip() for item in os.getenv("PLATFORM_ADMIN_CLERK_IDS", "").split(",") if item.strip()}
    subject = claims.get("sub")
    if not allowed or not subject or subject not in allowed:
        raise HTTPException(status_code=403, detail={"error": "Platform admin access required", "code": "platform_admin_required"})
    return subject


@lru_cache
def platform_session_factory() -> sessionmaker[Session]:
    url = os.getenv("PLATFORM_DATABASE_URL", "")
    if not url:
        raise RuntimeError("PLATFORM_DATABASE_URL must be configured separately from DATABASE_URL")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    # Explicit refusal prevents accidental use of a gym operational database.
    gym_db_url = os.getenv("DATABASE_URL", "")
    if gym_db_url and url.replace("postgresql+psycopg://", "postgresql://") == gym_db_url.replace("postgresql+psycopg://", "postgresql://"):
        raise RuntimeError("Platform and gym DATABASE_URL must not be the same")
    return sessionmaker(bind=create_engine(url, pool_pre_ping=True), expire_on_commit=False)


def platform_db() -> Generator[Session, None, None]:
    try:
        with platform_session_factory()() as session:
            yield session
    except RuntimeError:
        raise HTTPException(status_code=503, detail={"error": "Platform database is not configured", "code": "platform_database_unavailable"}) from None


app = FastAPI(title="MyGym Platform Admin API", version="0.1.0", docs_url=None, redoc_url=None)


@app.get("/api/platform/healthz", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/platform/gyms", response_model=list[GymView])
def list_gyms(actor: str = Depends(require_platform_admin), db: Session = Depends(platform_db)) -> list[GymView]:
    return [GymView.from_tenant(gym) for gym in db.scalars(select(GymTenant).order_by(GymTenant.name)).all()]


@app.post("/api/platform/gyms", response_model=GymView, status_code=status.HTTP_201_CREATED)
def register_gym(payload: GymCreate, actor: str = Depends(require_platform_admin), db: Session = Depends(platform_db)) -> GymView:
    gym = GymTenant(name=payload.name.strip(), slug=payload.slug, owner_clerk_user_id=payload.owner_clerk_user_id)
    try:
        db.add(gym)
        db.flush()
        db.add(PlatformAudit(actor_clerk_user_id=actor, gym_id=gym.id, event="gym_registered"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"error": "Gym slug is already registered", "code": "gym_slug_exists"}) from None
    db.refresh(gym)
    return GymView.from_tenant(gym)


@app.get("/api/platform/gyms/{gym_id}", response_model=GymView)
def get_gym(gym_id: str, actor: str = Depends(require_platform_admin), db: Session = Depends(platform_db)) -> GymView:
    gym = db.get(GymTenant, gym_id)
    if not gym:
        raise HTTPException(status_code=404, detail={"error": "Gym not found", "code": "gym_not_found"})
    return GymView.from_tenant(gym)
