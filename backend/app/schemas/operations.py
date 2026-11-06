from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.models.member import MemberStatus
from backend.app.models.payment import PaymentMethod, PaymentStatus
from backend.app.schemas.base import ApiModel


_KENYAN_PHONE = re.compile(r"^(?:\+254|0)(?:7|1)\d{8}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_phone(value: str) -> str:
    normalized = re.sub(r"[\s()-]", "", value)
    if normalized.startswith("0") and len(normalized) == 10:
        normalized = "+254" + normalized[1:]
    elif normalized.startswith("254") and len(normalized) == 12:
        normalized = "+" + normalized
    if not _KENYAN_PHONE.fullmatch(normalized):
        raise ValueError("Enter a valid Kenyan mobile number")
    return normalized


class FitnessAssessmentInput(ApiModel):
    weight_kg: float | None = Field(default=None, gt=0, le=500, allow_inf_nan=False)
    height_cm: float | None = Field(default=None, gt=0, le=300, allow_inf_nan=False)
    body_fat_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    muscle_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    visceral_fat_level: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def at_least_one_measurement(self) -> "FitnessAssessmentInput":
        if all(getattr(self, field) is None for field in (
            "weight_kg", "height_cm", "body_fat_percent", "muscle_percent", "visceral_fat_level"
        )):
            raise ValueError("Enter at least one fitness measurement or skip the assessment")
        return self


class FitnessAssessmentResponse(FitnessAssessmentInput):
    id: UUID
    recorded_at: datetime
    bmi: float | None = None


class FitnessAssessmentHistoryItem(ApiModel):
    id: UUID
    recorded_at: datetime
    weight_kg: float | None = None
    height_cm: float | None = None
    bmi: float | None = None
    body_fat_percent: float | None = None
    muscle_percent: float | None = None
    visceral_fat_level: float | None = None


class FitnessAssessmentHistory(ApiModel):
    items: list[FitnessAssessmentHistoryItem]


class FitnessAssessmentRecordInput(FitnessAssessmentInput):
    pass


class FitnessAssessmentSaved(FitnessAssessmentHistoryItem):
    pass


class MemberInput(ApiModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=9, max_length=20)
    email: str | None = Field(default=None, max_length=320)
    initial_assessment: FitnessAssessmentInput | None = None

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Full name must contain at least two characters")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_member_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class MemberUpdate(ApiModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, min_length=9, max_length=20)
    email: str | None = Field(default=None, max_length=320)
    status: MemberStatus | None = None

    @model_validator(mode="before")
    @classmethod
    def require_update_values(cls, values: object) -> object:
        if not isinstance(values, dict) or not values:
            raise ValueError("At least one member field must be provided")
        if any(key != "email" and value is None for key, value in values.items()):
            raise ValueError("Member fields cannot be cleared with null values")
        return values

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Full name must contain at least two characters")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_member_phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value is not None else None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if not _EMAIL.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class MemberSummary(ApiModel):
    id: UUID
    member_number: str
    full_name: str
    phone: str
    email: str | None
    status: MemberStatus
    registered_at: datetime
    initials: str


class MemberDetail(MemberSummary):
    qr_token: str
    onboarding_token: str | None = None
    latest_assessment: FitnessAssessmentResponse | None = None


class MemberQr(ApiModel):
    member_id: UUID
    member_number: str
    qr_token: str
    rotated_at: datetime


class MemberPage(ApiModel):
    items: list[MemberSummary]
    total: int
    page: int
    page_size: int


class AccessWindowInput(ApiModel):
    weekday: int = Field(ge=0, le=6)
    starts_at: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    ends_at: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

    @model_validator(mode="after")
    def validate_window(self) -> "AccessWindowInput":
        if self.starts_at >= self.ends_at:
            raise ValueError("Access window end must be later than its start")
        return self


class AccessWindow(AccessWindowInput):
    id: UUID


def validate_weekly_windows(windows: list[AccessWindowInput]) -> None:
    weekdays = [window.weekday for window in windows]
    if len(weekdays) != len(set(weekdays)):
        raise ValueError("Only one access window may be set for each day")


class MembershipPlanInput(ApiModel):
    name: str = Field(min_length=2, max_length=100)
    monthly_price_kes: int = Field(ge=1, le=1_000_000)
    is_active: bool
    access_windows: list[AccessWindowInput]

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Plan name must contain at least two characters")
        return normalized

    @model_validator(mode="after")
    def validate_plan(self) -> "MembershipPlanInput":
        validate_weekly_windows(self.access_windows)
        if self.is_active and not self.access_windows:
            raise ValueError("Active plans need at least one configured access window")
        return self


class MembershipPlanUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    monthly_price_kes: int | None = Field(default=None, ge=1, le=1_000_000)
    is_active: bool | None = None
    access_windows: list[AccessWindowInput] | None = None

    @model_validator(mode="before")
    @classmethod
    def require_update_values(cls, values: object) -> object:
        if not isinstance(values, dict) or not values:
            raise ValueError("At least one plan field must be provided")
        if any(value is None for value in values.values()):
            raise ValueError("Plan fields cannot be cleared with null values")
        return values

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Plan name must contain at least two characters")
        return normalized

    @model_validator(mode="after")
    def validate_windows(self) -> "MembershipPlanUpdate":
        if self.access_windows is not None:
            validate_weekly_windows(self.access_windows)
        return self


class MembershipPlanResponse(ApiModel):
    id: UUID
    name: str
    monthly_price_kes: int
    is_active: bool
    schedule_configured: bool
    access_windows: list[AccessWindow]
    created_at: datetime
    updated_at: datetime


# MYGYM_UPGRADE_V1 — staff-confirmed upgrade, never treated as M-Pesa verification.
class MembershipUpgradeInput(ApiModel):
    to_plan_id: UUID
    method: PaymentMethod
    reference: str = Field(min_length=3, max_length=80)

    @field_validator("reference")
    @classmethod
    def trim_reference(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a payment reference of at least three characters")
        return value


class MembershipUpgradeResponse(ApiModel):
    id: UUID
    subscription_id: UUID
    from_plan_name: str
    to_plan_name: str
    topup_kes: int
    payment_id: UUID
    expires_on: date


class SubscriptionInput(ApiModel):
    plan_id: UUID
    starts_on: date = Field(
        description="Inclusive first access date in the gym's local calendar."
    )


class SubscriptionResponse(ApiModel):
    id: UUID
    member_id: UUID
    member_name: str
    member_number: str
    plan_id: UUID
    plan_name: str
    monthly_price_kes: int
    starts_on: date = Field(
        description="Inclusive first access date in the gym's local calendar."
    )
    expires_on: date = Field(
        description=(
            "Inclusive final access date. The term ends the day before the same "
            "calendar date in the following month, clamped to that month's last day."
        )
    )
    status: Literal["scheduled", "active", "expired", "cancelled"]
    created_at: datetime


class SubscriptionPage(ApiModel):
    items: list[SubscriptionResponse]
    total: int
    page: int
    page_size: int


class PaymentInput(ApiModel):
    member_id: UUID
    subscription_id: UUID | None = None
    amount_kes: int = Field(ge=1, le=1_000_000)
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=80)
    paid_at: datetime | None = None

    @field_validator("reference")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @model_validator(mode="after")
    def require_manual_mpesa_reference(self) -> "PaymentInput":
        if self.method == PaymentMethod.MPESA_MANUAL and not self.reference:
            raise ValueError("Enter the M-Pesa transaction reference")
        return self


class PaymentVoidInput(ApiModel):
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 5:
            raise ValueError("Give a reason with at least five characters")
        return normalized


class PaymentResponse(ApiModel):
    id: UUID
    member_id: UUID
    member_name: str
    member_number: str
    subscription_id: UUID | None
    amount_kes: int
    currency: Literal["KES"] = "KES"
    method: PaymentMethod
    reference: str | None
    status: PaymentStatus
    verification_status: Literal["staff_recorded"] = "staff_recorded"
    paid_at: datetime
    recorded_by_name: str
    created_at: datetime
    void_reason: str | None


class PaymentPage(ApiModel):
    items: list[PaymentResponse]
    total: int
    page: int
    page_size: int


class AttendanceLookupInput(ApiModel):
    member_id: UUID | None = None
    qr_token: str | None = Field(default=None, min_length=32, max_length=128)

    @model_validator(mode="after")
    def require_one_lookup_identifier(self) -> "AttendanceLookupInput":
        if (self.member_id is None) == (self.qr_token is None):
            raise ValueError("Provide either a member ID or QR token")
        return self


class AttendanceRestriction(ApiModel):
    code: Literal[
        "member_inactive",
        "no_subscription",
        "expired",
        "plan_inactive",
        "outside_hours",
        "duplicate",
    ]
    message: str
    override_allowed: bool


class AttendanceReview(ApiModel):
    member: MemberSummary
    subscription: SubscriptionResponse | None
    plan: MembershipPlanResponse | None
    checked_at: datetime
    restrictions: list[AttendanceRestriction]
    can_check_in: bool
    duplicate_check_in_at: datetime | None


class CheckInInput(ApiModel):
    member_id: UUID
    confirmed: Literal[True]
    source: Literal["qr", "manual"]


class CheckInOverrideInput(ApiModel):
    member_id: UUID
    confirmed: Literal[True]
    source: Literal["qr", "manual"]
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 5:
            raise ValueError("Give a reason with at least five characters")
        return normalized


class CheckInResponse(ApiModel):
    id: UUID
    member_id: UUID
    member_name: str
    member_number: str
    checked_in_at: datetime
    source: Literal["qr", "manual"]
    was_overridden: bool
    override_reason: str | None
    restriction_codes: list[str]
    staff_name: str


class CheckInPage(ApiModel):
    items: list[CheckInResponse]
    total: int
    page: int
    page_size: int
