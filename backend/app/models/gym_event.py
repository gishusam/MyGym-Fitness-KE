from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class GymEvent(Base):
    __tablename__ = "gym_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'cancelled')",
            name="gym_events_status_check",
        ),
        CheckConstraint("capacity BETWEEN 1 AND 10000", name="gym_events_capacity_check"),
        CheckConstraint(
            "confirmed_count BETWEEN 0 AND capacity",
            name="gym_events_confirmed_count_check",
        ),
        CheckConstraint("ends_at > starts_at", name="gym_events_period_check"),
        CheckConstraint(
            "cover_size_bytes IS NULL OR cover_size_bytes BETWEEN 1 AND 10485760",
            name="gym_events_cover_size_check",
        ),
        Index("ix_gym_events_status_starts", "status", "starts_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    instructor_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    cover_storage_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    cover_filename: Mapped[str | None] = mapped_column(String(180))
    cover_media_type: Mapped[str | None] = mapped_column(String(64))
    cover_size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "member_id", name="event_registrations_event_member_unique"),
        CheckConstraint(
            "status IN ('confirmed', 'cancelled')",
            name="event_registrations_status_check",
        ),
        Index("ix_event_registrations_event_status", "event_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gym_events.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    registered_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="confirmed", server_default="confirmed"
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
