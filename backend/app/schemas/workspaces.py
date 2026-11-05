from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.base import ApiModel
from backend.app.schemas.operations import FitnessAssessmentHistoryItem


StaffRoleInput = Literal["receptionist", "trainer"]
StaffStatusInput = Literal["active", "inactive"]
WorkoutStatus = Literal["active", "archived"]
AssignmentStatus = Literal["assigned", "in_progress", "completed", "cancelled"]
EventStatus = Literal["draft", "published", "cancelled"]


class StaffMember(ApiModel):
    id: UUID
    name: str
    email: str
    role: str
    status: str
    created_at: datetime


class StaffCreateInput(ApiModel):
    email: str = Field(min_length=5, max_length=320)
    role: StaffRoleInput

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address")
        return normalized


class StaffUpdateInput(ApiModel):
    role: StaffRoleInput | None = None
    status: StaffStatusInput | None = None

    @model_validator(mode="after")
    def require_update(self) -> "StaffUpdateInput":
        if not self.model_fields_set:
            raise ValueError("Provide a role or status to update")
        return self


class AttendanceDay(ApiModel):
    day: date
    check_ins: int


class ExpiringMembership(ApiModel):
    member_id: UUID
    member_number: str
    full_name: str
    expires_on: date
    days_remaining: int


class TrainerMember(ApiModel):
    id: UUID
    member_number: str
    full_name: str
    status: str
    assessment_count: int
    latest_assessment: FitnessAssessmentHistoryItem | None = None


class WorkoutExerciseInput(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    sets: int = Field(default=1, ge=1, le=50)
    repetitions: int | None = Field(default=None, ge=1, le=1000)
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    rest_seconds: int | None = Field(default=None, ge=0, le=3600)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def require_target(self) -> "WorkoutExerciseInput":
        if self.repetitions is None and self.duration_seconds is None:
            raise ValueError("Enter repetitions or a duration for each exercise")
        return self


class WorkoutProgramInput(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    goal: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    exercises: list[WorkoutExerciseInput] = Field(min_length=1, max_length=30)

    @field_validator("name", "goal")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class WorkoutProgramUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    goal: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: WorkoutStatus | None = None
    exercises: list[WorkoutExerciseInput] | None = Field(default=None, min_length=1, max_length=30)

    @model_validator(mode="after")
    def require_update(self) -> "WorkoutProgramUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one workout field to update")
        return self


class WorkoutExerciseResponse(ApiModel):
    id: UUID
    position: int
    name: str
    sets: int
    repetitions: int | None
    duration_seconds: int | None
    rest_seconds: int | None


class WorkoutResourceResponse(ApiModel):
    id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    created_at: datetime
    download_url: str


class WorkoutProgramResponse(ApiModel):
    id: UUID
    name: str
    goal: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    exercises: list[WorkoutExerciseResponse]
    resources: list[WorkoutResourceResponse]


class WorkoutAssignmentInput(ApiModel):
    member_id: UUID
    starts_on: date
    notes: str | None = Field(default=None, max_length=1000)


class WorkoutAssignmentUpdate(ApiModel):
    status: AssignmentStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_update(self) -> "WorkoutAssignmentUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide an assignment status or note to update")
        return self


class WorkoutAssignmentResponse(ApiModel):
    id: UUID
    program_id: UUID
    program_name: str
    goal: str
    member_id: UUID
    member_number: str
    member_name: str
    starts_on: date
    status: str
    notes: str | None
    created_at: datetime


class EventInput(ApiModel):
    name: str = Field(min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(ge=1, le=10000)
    instructor_staff_id: UUID | None = None
    status: EventStatus = "draft"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def validate_period(self) -> "EventInput":
        if (self.starts_at.tzinfo is None) != (self.ends_at.tzinfo is None):
            raise ValueError("Event start and end must use the same time-zone format")
        if self.ends_at <= self.starts_at:
            raise ValueError("Event end must be later than its start")
        return self


class EventUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    capacity: int | None = Field(default=None, ge=1, le=10000)
    instructor_staff_id: UUID | None = None
    status: EventStatus | None = None

    @model_validator(mode="after")
    def require_update(self) -> "EventUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one event field to update")
        return self


class EventResponse(ApiModel):
    id: UUID
    name: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    capacity: int
    instructor_staff_id: UUID | None
    instructor_name: str | None
    status: str
    registered_count: int
    remaining_slots: int
    cover_url: str | None
    created_at: datetime
    updated_at: datetime


class EventRegistrationInput(ApiModel):
    member_id: UUID


class EventRegistrationResponse(ApiModel):
    id: UUID
    event_id: UUID
    member_id: UUID
    member_number: str
    member_name: str
    status: str
    registered_at: datetime


class EventMember(ApiModel):
    id: UUID
    member_number: str
    full_name: str
    status: str


class DashboardSummary(ApiModel):
    role: str
    active_members: int | None = None
    new_members_last_30_days: int | None = None
    revenue_this_month_kes: int | None = None
    payments_this_month: int | None = None
    memberships_expiring: list[ExpiringMembership] = Field(default_factory=list)
    inactive_members: int | None = None
    check_ins_today: int | None = None
    attendance_trend: list[AttendanceDay] = Field(default_factory=list)
    staff_count: int | None = None
    trainer_member_count: int | None = None
    recent_assessments: int | None = None
    assigned_workouts: int | None = None
    upcoming_events: list[EventResponse] = Field(default_factory=list)
