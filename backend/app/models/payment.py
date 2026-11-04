from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class PaymentStatus(StrEnum):
    RECORDED = "recorded"
    VOIDED = "voided"


class PaymentMethod(StrEnum):
    MPESA_MANUAL = "mpesa_manual"
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_kes > 0", name="payments_amount_check"),
        CheckConstraint(
            "method IN ('mpesa_manual', 'cash', 'bank_transfer')",
            name="payments_method_check",
        ),
        CheckConstraint(
            "status IN ('recorded', 'voided')", name="payments_status_check"
        ),
        CheckConstraint(
            "method != 'mpesa_manual' OR reference IS NOT NULL",
            name="payments_mpesa_reference_check",
        ),
        UniqueConstraint("reference", name="payments_reference_unique"),
        Index("ix_payments_member_paid_at", "member_id", "paid_at"),
        Index("ix_payments_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    amount_kes: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.RECORDED.value
    )
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True
    )
    voided_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
