"""Add member, membership, payment, and attendance operations.

Revision ID: 0002_daily_operations
Revises: 0001_foundation
Create Date: 2026-11-04
"""

from collections.abc import Sequence
from datetime import time
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_daily_operations"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OFF_PEAK_ID = UUID("7a938f52-3073-4cac-94d3-eae8b08e31fa")
_PEAK_ID = UUID("c35ec58e-1762-4057-9a7d-8ab7bdbf9102")


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_number", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("qr_token", sa.String(length=128), nullable=False),
        sa.Column(
            "registered_at",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_number", name="members_member_number_unique"),
        sa.UniqueConstraint("phone", name="members_phone_unique"),
        sa.UniqueConstraint("qr_token", name="members_qr_token_unique"),
    )
    op.create_index("ix_members_full_name", "members", ["full_name"], unique=False)
    op.create_index("ix_members_registered_at", "members", ["registered_at"], unique=False)

    op.create_table(
        "membership_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("monthly_price_kes", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_by_staff_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "updated_by_staff_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
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
            "monthly_price_kes BETWEEN 1 AND 1000000",
            name="membership_plans_price_check",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="membership_plans_name_unique"),
    )
    op.create_index(
        "ix_membership_plans_active", "membership_plans", ["is_active"], unique=False
    )

    op.create_table(
        "plan_access_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.Time(), nullable=False),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name="plan_access_windows_weekday_check"
        ),
        sa.CheckConstraint(
            "starts_at < ends_at", name="plan_access_windows_time_check"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["membership_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id", "weekday", name="plan_access_windows_plan_day_unique"
        ),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_name", sa.String(length=100), nullable=False),
        sa.Column("monthly_price_kes", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("created_by_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_on >= starts_on", name="subscriptions_period_check"
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'active', 'cancelled')",
            name="subscriptions_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["membership_plans.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscriptions_member_period",
        "subscriptions",
        ["member_id", "starts_on", "expires_on"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions_status", "subscriptions", ["status"], unique=False
    )

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount_kes", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("reference", sa.String(length=80), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'recorded'"), nullable=False
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("voided_by_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount_kes > 0", name="payments_amount_check"),
        sa.CheckConstraint(
            "method IN ('mpesa_manual', 'cash', 'bank_transfer')",
            name="payments_method_check",
        ),
        sa.CheckConstraint(
            "status IN ('recorded', 'voided')", name="payments_status_check"
        ),
        sa.CheckConstraint(
            "method != 'mpesa_manual' OR reference IS NOT NULL",
            name="payments_mpesa_reference_check",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["members.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["voided_by_staff_id"], ["staff_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="payments_reference_unique"),
    )
    op.create_index(
        "ix_payments_member_paid_at",
        "payments",
        ["member_id", "paid_at"],
        unique=False,
    )
    op.create_index("ix_payments_status", "payments", ["status"], unique=False)

    op.create_table(
        "check_ins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "checked_in_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "source", sa.String(length=12), server_default=sa.text("'manual'"), nullable=False
        ),
        sa.Column(
            "was_overridden",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("override_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "restriction_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('qr', 'manual')", name="check_ins_source_check"
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_check_ins_member_checked_at",
        "check_ins",
        ["member_id", "checked_in_at"],
        unique=False,
    )
    op.create_index(
        "ix_check_ins_checked_at", "check_ins", ["checked_in_at"], unique=False
    )

    plans = sa.table(
        "membership_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("monthly_price_kes", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        plans,
        [
            {
                "id": _OFF_PEAK_ID,
                "name": "Off-Peak",
                "monthly_price_kes": 4000,
                "is_active": True,
            },
            {
                "id": _PEAK_ID,
                "name": "Peak Access",
                "monthly_price_kes": 5000,
                "is_active": False,
            },
        ],
    )
    windows = sa.table(
        "plan_access_windows",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("plan_id", postgresql.UUID(as_uuid=True)),
        sa.column("weekday", sa.Integer()),
        sa.column("starts_at", sa.Time()),
        sa.column("ends_at", sa.Time()),
    )
    op.bulk_insert(
        windows,
        [
            {
                "id": uuid5(NAMESPACE_URL, f"mygym:off-peak:{weekday}"),
                "plan_id": _OFF_PEAK_ID,
                "weekday": weekday,
                "starts_at": time(9, 0),
                "ends_at": time(15, 0),
            }
            for weekday in range(7)
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_check_ins_checked_at", table_name="check_ins")
    op.drop_index("ix_check_ins_member_checked_at", table_name="check_ins")
    op.drop_table("check_ins")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_member_paid_at", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_member_period", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("plan_access_windows")
    op.drop_index("ix_membership_plans_active", table_name="membership_plans")
    op.drop_table("membership_plans")
    op.drop_index("ix_members_registered_at", table_name="members")
    op.drop_index("ix_members_full_name", table_name="members")
    op.drop_table("members")
