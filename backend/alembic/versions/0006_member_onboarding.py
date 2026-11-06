"""Add secure member onboarding and structured workout matching metadata."""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_member_onboarding"
down_revision: str | None = "0005_workspaces_workouts_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "workout_programs",
        sa.Column("goals_supported", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "workout_programs",
        sa.Column("minimum_experience", sa.String(20), server_default="beginner", nullable=False),
    )
    op.add_column(
        "workout_programs",
        sa.Column("maximum_experience", sa.String(20), server_default="advanced", nullable=False),
    )
    op.add_column(
        "workout_programs",
        sa.Column("recommended_days_per_week", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "workout_programs",
        sa.Column("expected_session_minutes", sa.Integer(), server_default="45", nullable=False),
    )
    op.add_column(
        "workout_programs",
        sa.Column("equipment_requirements", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "workout_programs",
        sa.Column("trainer_review_required", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "workout_programs_minimum_experience_check",
        "workout_programs",
        "minimum_experience IN ('beginner', 'intermediate', 'advanced')",
    )
    op.create_check_constraint(
        "workout_programs_maximum_experience_check",
        "workout_programs",
        "maximum_experience IN ('beginner', 'intermediate', 'advanced')",
    )
    op.create_check_constraint(
        "workout_programs_days_per_week_check",
        "workout_programs",
        "recommended_days_per_week BETWEEN 1 AND 7",
    )
    op.create_check_constraint(
        "workout_programs_session_minutes_check",
        "workout_programs",
        "expected_session_minutes BETWEEN 15 AND 240",
    )

    op.create_table(
        "member_onboarding_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "member_id",
            UUID,
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_member_onboarding_tokens_member_expiry",
        "member_onboarding_tokens",
        ["member_id", "expires_at"],
    )
    op.create_index(
        "ix_member_onboarding_tokens_expiry",
        "member_onboarding_tokens",
        ["expires_at"],
    )

    op.create_table(
        "member_fitness_profiles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "member_id",
            UUID,
            sa.ForeignKey("members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("primary_goal", sa.String(40), nullable=False),
        sa.Column("experience", sa.String(20), nullable=False),
        sa.Column("available_days_per_week", sa.Integer(), nullable=False),
        sa.Column("session_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("equipment_preferences", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("limitations", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(24), server_default="awaiting_review", nullable=False),
        sa.Column(
            "recommended_program_id",
            UUID,
            sa.ForeignKey("workout_programs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("alternative_program_ids", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "final_program_id",
            UUID,
            sa.ForeignKey("workout_programs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workout_assignment_id",
            UUID,
            sa.ForeignKey("workout_assignments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_staff_id",
            UUID,
            sa.ForeignKey("staff_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("member_id", name="member_fitness_profiles_member_unique"),
        sa.CheckConstraint(
            "experience IN ('beginner', 'intermediate', 'advanced')",
            name="member_fitness_profiles_experience_check",
        ),
        sa.CheckConstraint(
            "available_days_per_week BETWEEN 1 AND 7",
            name="member_fitness_profiles_days_check",
        ),
        sa.CheckConstraint(
            "session_duration_minutes BETWEEN 15 AND 180",
            name="member_fitness_profiles_duration_check",
        ),
        sa.CheckConstraint(
            "review_status IN ('awaiting_review', 'trainer_approved')",
            name="member_fitness_profiles_review_status_check",
        ),
    )
    op.create_index(
        "ix_member_fitness_profiles_review_status",
        "member_fitness_profiles",
        ["review_status", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_member_fitness_profiles_review_status", table_name="member_fitness_profiles")
    op.drop_table("member_fitness_profiles")
    op.drop_index("ix_member_onboarding_tokens_expiry", table_name="member_onboarding_tokens")
    op.drop_index("ix_member_onboarding_tokens_member_expiry", table_name="member_onboarding_tokens")
    op.drop_table("member_onboarding_tokens")
    op.drop_constraint(
        "workout_programs_session_minutes_check", "workout_programs", type_="check"
    )
    op.drop_constraint(
        "workout_programs_days_per_week_check", "workout_programs", type_="check"
    )
    op.drop_constraint(
        "workout_programs_maximum_experience_check", "workout_programs", type_="check"
    )
    op.drop_constraint(
        "workout_programs_minimum_experience_check", "workout_programs", type_="check"
    )
    for column in (
        "trainer_review_required",
        "equipment_requirements",
        "expected_session_minutes",
        "recommended_days_per_week",
        "maximum_experience",
        "minimum_experience",
        "goals_supported",
    ):
        op.drop_column("workout_programs", column)
