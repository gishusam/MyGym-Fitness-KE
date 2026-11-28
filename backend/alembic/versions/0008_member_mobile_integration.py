"""Add member Clerk links and persisted mobile workout sessions.

Revision ID: 0008_member_mobile_integration
Revises: 0007_member_workout_links
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_member_mobile_integration"
down_revision: str | None = "0007_member_workout_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("members", sa.Column("clerk_user_id", sa.String(128), nullable=True))
    op.create_index(
        "uq_members_clerk_user_id", "members", ["clerk_user_id"], unique=True
    )
    op.create_table(
        "workout_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "assignment_id",
            UUID,
            sa.ForeignKey("workout_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            UUID,
            sa.ForeignKey("members.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(20), server_default="in_progress", nullable=False
        ),
        sa.Column(
            "exercises",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "assignment_id",
            "session_date",
            name="workout_sessions_assignment_date_unique",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed')",
            name="workout_sessions_status_check",
        ),
    )
    op.create_index(
        "ix_workout_sessions_member_date",
        "workout_sessions",
        ["member_id", "session_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_workout_sessions_member_date", table_name="workout_sessions")
    op.drop_table("workout_sessions")
    op.drop_index("uq_members_clerk_user_id", table_name="members")
    op.drop_column("members", "clerk_user_id")
