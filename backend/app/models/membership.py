from __future__ import annotations

import uuid
from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class SubscriptionStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CANCELLED = "cancelled"


class MembershipPlan(Base):
    __tablename__ = "membership_plans"
    __table_args__ = (
        CheckConstraint("monthly_price_kes BETWEEN 1 AND 1000000", name="membership_plans_price_check"),
        Index("ix_membership_plans_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    monthly_price_kes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True
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


class PlanAccessWindow(Base):
    __tablename__ = "plan_access_windows"
    __table_args__ = (
        UniqueConstraint("plan_id", "weekday", name="plan_access_windows_plan_day_unique"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="plan_access_windows_weekday_check"),
        CheckConstraint("starts_at < ends_at", name="plan_access_windows_time_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("membership_plans.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[time] = mapped_column(Time, nullable=False)
    ends_at: Mapped[time] = mapped_column(Time, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("expires_on >= starts_on", name="subscriptions_period_check"),
        CheckConstraint(
            "status IN ('scheduled', 'active', 'cancelled')",
            name="subscriptions_status_check",
        ),
        Index("ix_subscriptions_member_period", "member_id", "starts_on", "expires_on"),
        Index("ix_subscriptions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False
    )
    plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_price_kes: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubscriptionStatus.ACTIVE.value
    )
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
