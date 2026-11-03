from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class GymSettings(Base):
    __tablename__ = "gym_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="gym_settings_singleton_check"),
        CheckConstraint(
            "attendance_duplicate_interval_minutes BETWEEN 1 AND 120",
            name="gym_settings_duplicate_interval_check",
        ),
        CheckConstraint(
            "inactivity_threshold_days BETWEEN 1 AND 90",
            name="gym_settings_inactivity_threshold_check",
        ),
        CheckConstraint(
            "renewal_reminder_days_before BETWEEN 1 AND 30",
            name="gym_settings_renewal_reminder_check",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    gym_name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="Africa/Nairobi"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="KES"
    )
    attendance_duplicate_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="5"
    )
    inactivity_threshold_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="14"
    )
    renewal_reminder_days_before: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    peak_access_hours_configured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    owner_bootstrap_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
