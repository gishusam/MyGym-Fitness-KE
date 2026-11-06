from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class WorkoutProgram(Base):
    __tablename__ = "workout_programs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="workout_programs_status_check",
        ),
        CheckConstraint(
            "minimum_experience IN ('beginner', 'intermediate', 'advanced')",
            name="workout_programs_minimum_experience_check",
        ),
        CheckConstraint(
            "maximum_experience IN ('beginner', 'intermediate', 'advanced')",
            name="workout_programs_maximum_experience_check",
        ),
        CheckConstraint(
            "recommended_days_per_week BETWEEN 1 AND 7",
            name="workout_programs_days_per_week_check",
        ),
        CheckConstraint(
            "expected_session_minutes BETWEEN 15 AND 240",
            name="workout_programs_session_minutes_check",
        ),
        Index("ix_workout_programs_status_name", "status", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    goals_supported: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    minimum_experience: Mapped[str] = mapped_column(
        String(20), nullable=False, default="beginner", server_default="beginner"
    )
    maximum_experience: Mapped[str] = mapped_column(
        String(20), nullable=False, default="advanced", server_default="advanced"
    )
    recommended_days_per_week: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    expected_session_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=45, server_default="45"
    )
    equipment_requirements: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    trainer_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
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


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        CheckConstraint("position >= 0", name="workout_exercises_position_check"),
        CheckConstraint("sets BETWEEN 1 AND 50", name="workout_exercises_sets_check"),
        CheckConstraint(
            "repetitions IS NULL OR repetitions BETWEEN 1 AND 1000",
            name="workout_exercises_repetitions_check",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 1 AND 86400",
            name="workout_exercises_duration_check",
        ),
        CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 3600",
            name="workout_exercises_rest_check",
        ),
        UniqueConstraint(
            "program_id", "position", name="workout_exercises_program_position_unique"
        ),
        Index("ix_workout_exercises_program", "program_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workout_programs.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sets: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    repetitions: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    rest_seconds: Mapped[int | None] = mapped_column(Integer)


class WorkoutAssignment(Base):
    __tablename__ = "workout_assignments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('assigned', 'in_progress', 'completed', 'cancelled')",
            name="workout_assignments_status_check",
        ),
        Index("ix_workout_assignments_member_status", "member_id", "status"),
        Index("ix_workout_assignments_program_status", "program_id", "status"),
        Index(
            "uq_workout_assignment_active_member_program",
            "program_id",
            "member_id",
            unique=True,
            postgresql_where=text("status IN ('assigned', 'in_progress')"),
            sqlite_where=text("status IN ('assigned', 'in_progress')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workout_programs.id", ondelete="RESTRICT"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="assigned", server_default="assigned"
    )
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkoutResource(Base):
    __tablename__ = "workout_resources"
    __table_args__ = (
        CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="workout_resources_size_check"),
        Index("ix_workout_resources_program", "program_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workout_programs.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
