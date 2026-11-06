from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
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


class MemberOnboardingToken(Base):
    __tablename__ = "member_onboarding_tokens"
    __table_args__ = (
        Index("ix_member_onboarding_tokens_member_expiry", "member_id", "expires_at"),
        Index("ix_member_onboarding_tokens_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemberFitnessProfile(Base):
    __tablename__ = "member_fitness_profiles"
    __table_args__ = (
        UniqueConstraint("member_id", name="member_fitness_profiles_member_unique"),
        CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')",
            name="member_fitness_profiles_experience_check",
        ),
        CheckConstraint(
            "available_days_per_week BETWEEN 1 AND 7",
            name="member_fitness_profiles_days_check",
        ),
        CheckConstraint(
            "session_duration_minutes BETWEEN 15 AND 180",
            name="member_fitness_profiles_duration_check",
        ),
        CheckConstraint(
            "review_status IN ('awaiting_review', 'trainer_approved')",
            name="member_fitness_profiles_review_status_check",
        ),
        Index("ix_member_fitness_profiles_review_status", "review_status", "submitted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    primary_goal: Mapped[str] = mapped_column(String(40), nullable=False)
    experience: Mapped[str] = mapped_column(String(20), nullable=False)
    available_days_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    session_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    equipment_preferences: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="'[]'"
    )
    limitations: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="awaiting_review", server_default="awaiting_review"
    )
    recommended_program_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workout_programs.id", ondelete="SET NULL")
    )
    alternative_program_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="'[]'"
    )
    final_program_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workout_programs.id", ondelete="SET NULL")
    )
    workout_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workout_assignments.id", ondelete="SET NULL")
    )
    reviewed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
