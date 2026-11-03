from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.base import ApiModel


class GymSettingsResponse(ApiModel):
    gym_name: str
    timezone: str
    currency: str
    attendance_duplicate_interval_minutes: int
    inactivity_threshold_days: int
    renewal_reminder_days_before: int
    peak_access_hours_configured: bool
    updated_at: datetime


class GymSettingsUpdate(ApiModel):
    gym_name: str | None = Field(default=None, min_length=2, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    attendance_duplicate_interval_minutes: int | None = Field(
        default=None, ge=1, le=120
    )
    inactivity_threshold_days: int | None = Field(default=None, ge=1, le=90)
    renewal_reminder_days_before: int | None = Field(default=None, ge=1, le=30)

    @model_validator(mode="before")
    @classmethod
    def require_nonempty_and_nonnull_values(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        if not values:
            raise ValueError("At least one setting must be provided")
        if any(value is None for value in values.values()):
            raise ValueError("Settings cannot be cleared with null values")
        return values

    @field_validator("gym_name")
    @classmethod
    def normalize_gym_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Gym name must contain at least two characters")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Choose a valid timezone") from error
        return value
