"""Add staff workspaces, workout programs and gym events.

Revision ID: 0005_workspaces_workouts_events
Revises: 0004_membership_upgrades
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_workspaces_workouts_events"
down_revision: str | None = "0004_membership_upgrades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "workout_programs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("goal", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "created_by_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="workout_programs_status_check"),
    )
    op.create_index("ix_workout_programs_status_name", "workout_programs", ["status", "name"])

    op.create_table(
        "workout_exercises",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "program_id",
            UUID,
            sa.ForeignKey("workout_programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("rest_seconds", sa.Integer(), nullable=True),
        sa.CheckConstraint("position >= 0", name="workout_exercises_position_check"),
        sa.CheckConstraint("sets BETWEEN 1 AND 50", name="workout_exercises_sets_check"),
        sa.CheckConstraint(
            "repetitions IS NULL OR repetitions BETWEEN 1 AND 1000",
            name="workout_exercises_repetitions_check",
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 1 AND 86400",
            name="workout_exercises_duration_check",
        ),
        sa.CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 3600",
            name="workout_exercises_rest_check",
        ),
        sa.UniqueConstraint("program_id", "position", name="workout_exercises_program_position_unique"),
    )
    op.create_index("ix_workout_exercises_program", "workout_exercises", ["program_id", "position"])

    op.create_table(
        "workout_assignments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "program_id",
            UUID,
            sa.ForeignKey("workout_programs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            UUID,
            sa.ForeignKey("members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), server_default="assigned", nullable=False),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('assigned', 'in_progress', 'completed', 'cancelled')",
            name="workout_assignments_status_check",
        ),
    )
    op.create_index("ix_workout_assignments_member_status", "workout_assignments", ["member_id", "status"])
    op.create_index("ix_workout_assignments_program_status", "workout_assignments", ["program_id", "status"])
    op.create_index(
        "uq_workout_assignment_active_member_program",
        "workout_assignments",
        ["program_id", "member_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('assigned', 'in_progress')"),
    )

    op.create_table(
        "workout_resources",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "program_id",
            UUID,
            sa.ForeignKey("workout_programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(180), nullable=False),
        sa.Column("media_type", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False, unique=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_by_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="workout_resources_size_check"),
    )
    op.create_index("ix_workout_resources_program", "workout_resources", ["program_id"])

    op.create_table(
        "gym_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("confirmed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "instructor_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("cover_storage_key", sa.String(80), nullable=True, unique=True),
        sa.Column("cover_filename", sa.String(180), nullable=True),
        sa.Column("cover_media_type", sa.String(64), nullable=True),
        sa.Column("cover_size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'cancelled')",
            name="gym_events_status_check",
        ),
        sa.CheckConstraint("capacity BETWEEN 1 AND 10000", name="gym_events_capacity_check"),
        sa.CheckConstraint(
            "confirmed_count BETWEEN 0 AND capacity",
            name="gym_events_confirmed_count_check",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="gym_events_period_check"),
        sa.CheckConstraint(
            "cover_size_bytes IS NULL OR cover_size_bytes BETWEEN 1 AND 10485760",
            name="gym_events_cover_size_check",
        ),
    )
    op.create_index("ix_gym_events_status_starts", "gym_events", ["status", "starts_at"])

    op.create_table(
        "event_registrations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "event_id",
            UUID,
            sa.ForeignKey("gym_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            UUID,
            sa.ForeignKey("members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "registered_by_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), server_default="confirmed", nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('confirmed', 'cancelled')",
            name="event_registrations_status_check",
        ),
        sa.UniqueConstraint(
            "event_id", "member_id", name="event_registrations_event_member_unique"
        ),
    )
    op.create_index(
        "ix_event_registrations_event_status",
        "event_registrations",
        ["event_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_registrations_event_status", table_name="event_registrations")
    op.drop_table("event_registrations")
    op.drop_index("ix_gym_events_status_starts", table_name="gym_events")
    op.drop_table("gym_events")
    op.drop_index("ix_workout_resources_program", table_name="workout_resources")
    op.drop_table("workout_resources")
    op.drop_index("ix_workout_assignments_program_status", table_name="workout_assignments")
    op.drop_index(
        "uq_workout_assignment_active_member_program",
        table_name="workout_assignments",
    )
    op.drop_index("ix_workout_assignments_member_status", table_name="workout_assignments")
    op.drop_table("workout_assignments")
    op.drop_index("ix_workout_exercises_program", table_name="workout_exercises")
    op.drop_table("workout_exercises")
    op.drop_index("ix_workout_programs_status_name", table_name="workout_programs")
    op.drop_table("workout_programs")
