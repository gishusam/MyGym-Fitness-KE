from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class FitnessAssessment(Base):
    __tablename__ = "fitness_assessments"
    __table_args__ = (
        CheckConstraint("weight_kg IS NULL OR (weight_kg > 0 AND weight_kg <= 500)", name="fitness_weight_check"),
        CheckConstraint("height_cm IS NULL OR (height_cm > 0 AND height_cm <= 300)", name="fitness_height_check"),
        CheckConstraint("body_fat_percent IS NULL OR (body_fat_percent >= 0 AND body_fat_percent <= 100)", name="fitness_body_fat_check"),
        CheckConstraint("muscle_percent IS NULL OR (muscle_percent >= 0 AND muscle_percent <= 100)", name="fitness_muscle_check"),
        CheckConstraint("visceral_fat_level IS NULL OR (visceral_fat_level >= 0 AND visceral_fat_level <= 100)", name="fitness_visceral_check"),
        Index("ix_fitness_assessments_member_recorded", "member_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id", ondelete="RESTRICT"), nullable=False)
    recorded_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("staff_users.id", ondelete="SET NULL"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_cm: Mapped[float | None] = mapped_column(Float)
    bmi: Mapped[float | None] = mapped_column(Float)
    body_fat_percent: Mapped[float | None] = mapped_column(Float)
    muscle_percent: Mapped[float | None] = mapped_column(Float)
    visceral_fat_level: Mapped[float | None] = mapped_column(Float)
