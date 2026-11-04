from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class MemberStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        Index("ix_members_full_name", "full_name"),
        Index("ix_members_registered_at", "registered_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MemberStatus.ACTIVE.value
    )
    qr_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
