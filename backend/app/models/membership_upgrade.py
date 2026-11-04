from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base


class MembershipUpgrade(Base):
    __tablename__ = "membership_upgrades"
    __table_args__ = (UniqueConstraint("subscription_id", name="membership_upgrades_subscription_unique"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"), nullable=False)
    from_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False)
    from_plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    from_price_kes: Mapped[int] = mapped_column(Integer, nullable=False)
    to_plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False)
    to_plan_name: Mapped[str] = mapped_column(String(100), nullable=False)
    to_price_kes: Mapped[int] = mapped_column(Integer, nullable=False)
    topup_kes: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, unique=True)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
