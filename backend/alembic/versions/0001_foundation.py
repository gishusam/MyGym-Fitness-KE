"""Create the MyGym staff, settings, and audit foundation.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clerk_user_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
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
        sa.CheckConstraint(
            "role IN ('owner', 'receptionist', 'trainer')",
            name="staff_users_role_check",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="staff_users_status_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clerk_user_id", name="staff_users_clerk_user_id_key"),
    )
    op.create_index("ix_staff_users_email", "staff_users", ["email"], unique=False)
    op.create_table(
        "gym_settings",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("gym_name", sa.String(length=120), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=80),
            server_default=sa.text("'Africa/Nairobi'"),
            nullable=False,
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'KES'"),
            nullable=False,
        ),
        sa.Column(
            "attendance_duplicate_interval_minutes",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "inactivity_threshold_days",
            sa.Integer(),
            server_default=sa.text("14"),
            nullable=False,
        ),
        sa.Column(
            "renewal_reminder_days_before",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "peak_access_hours_configured",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "owner_bootstrap_completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="gym_settings_singleton_check"),
        sa.CheckConstraint(
            "attendance_duplicate_interval_minutes BETWEEN 1 AND 120",
            name="gym_settings_duplicate_interval_check",
        ),
        sa.CheckConstraint(
            "inactivity_threshold_days BETWEEN 1 AND 90",
            name="gym_settings_inactivity_threshold_check",
        ),
        sa.CheckConstraint(
            "renewal_reminder_days_before BETWEEN 1 AND 30",
            name="gym_settings_renewal_reminder_check",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["staff_users.id"],
            name="gym_settings_updated_by_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_staff_id"],
            ["staff_users.id"],
            name="audit_logs_actor_staff_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_actor_created",
        "audit_logs",
        ["actor_staff_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_logs_entity",
        "audit_logs",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO gym_settings (id, gym_name, timezone, currency)
            VALUES (1, 'MyGym Fitness KE', 'Africa/Nairobi', 'KES')
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("gym_settings")
    op.drop_index("ix_staff_users_email", table_name="staff_users")
    op.drop_table("staff_users")
