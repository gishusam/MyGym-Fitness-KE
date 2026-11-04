"""Add historical member fitness assessments.

Revision ID: 0003_fitness_assessments
Revises: 0002_daily_operations
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_fitness_assessments"
down_revision: str | None = "0002_daily_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fitness_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recorded_by_staff_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("staff_users.id", ondelete="SET NULL")),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("weight_kg", sa.Float()),
        sa.Column("height_cm", sa.Float()),
        sa.Column("bmi", sa.Float()),
        sa.Column("body_fat_percent", sa.Float()),
        sa.Column("muscle_percent", sa.Float()),
        sa.Column("visceral_fat_level", sa.Float()),
        sa.CheckConstraint("weight_kg IS NULL OR (weight_kg > 0 AND weight_kg <= 500)", name="fitness_weight_check"),
        sa.CheckConstraint("height_cm IS NULL OR (height_cm > 0 AND height_cm <= 300)", name="fitness_height_check"),
        sa.CheckConstraint("body_fat_percent IS NULL OR (body_fat_percent >= 0 AND body_fat_percent <= 100)", name="fitness_body_fat_check"),
        sa.CheckConstraint("muscle_percent IS NULL OR (muscle_percent >= 0 AND muscle_percent <= 100)", name="fitness_muscle_check"),
        sa.CheckConstraint("visceral_fat_level IS NULL OR (visceral_fat_level >= 0 AND visceral_fat_level <= 100)", name="fitness_visceral_check"),
    )
    op.create_index("ix_fitness_assessments_member_recorded", "fitness_assessments", ["member_id", "recorded_at"])


def downgrade() -> None:
    op.drop_index("ix_fitness_assessments_member_recorded", table_name="fitness_assessments")
    op.drop_table("fitness_assessments")
