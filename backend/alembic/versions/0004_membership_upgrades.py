"""Record audited member membership upgrades and top-up payment references.

Revision ID: 0004_membership_upgrades
Revises: 0003_fitness_assessments
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
revision: str = "0004_membership_upgrades"
down_revision: str | None = "0003_fitness_assessments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "membership_upgrades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("members.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_plan_name", sa.String(100), nullable=False),
        sa.Column("from_price_kes", sa.Integer(), nullable=False),
        sa.Column("to_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("to_plan_name", sa.String(100), nullable=False),
        sa.Column("to_price_kes", sa.Integer(), nullable=False),
        sa.Column("topup_kes", sa.Integer(), nullable=False),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subscription_id", name="membership_upgrades_subscription_unique"),
        sa.UniqueConstraint("payment_id", name="membership_upgrades_payment_id_key"),
        sa.CheckConstraint("topup_kes > 0", name="membership_upgrades_positive_topup"),
    )

def downgrade() -> None:
    op.drop_table("membership_upgrades")
