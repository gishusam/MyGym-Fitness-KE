from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend.app.schemas.base import ApiModel
from backend.app.schemas.operations import FitnessAssessmentHistoryItem
from backend.app.schemas.workspaces import EventResponse


class MemberMembership(ApiModel):
    id: UUID
    plan_name: str
    monthly_price_kes: int
    starts_on: date
    expires_on: date
    status: Literal["active", "scheduled", "expired", "cancelled"]


class MemberProfileResponse(ApiModel):
    id: UUID
    member_number: str
    full_name: str
    email: str | None
    phone: str
    status: str
    registered_at: datetime
    qr_token: str
    membership: MemberMembership | None
    check_ins_this_month: int


class MemberWorkoutExercise(ApiModel):
    id: UUID
    position: int
    name: str
    sets: int
    repetitions: int | None
    duration_seconds: int | None
    rest_seconds: int | None


class MemberWorkoutExerciseLogInput(ApiModel):
    exercise_id: UUID
    completed: bool
    weight_kg: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    reps_completed: int | None = Field(default=None, ge=0, le=1000)
    duration_seconds_completed: int | None = Field(default=None, ge=0, le=86400)


class MemberWorkoutExerciseLog(MemberWorkoutExerciseLogInput):
    pass


class MemberWorkoutSessionInput(ApiModel):
    exercises: list[MemberWorkoutExerciseLogInput] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_exercises(self) -> "MemberWorkoutSessionInput":
        ids = [item.exercise_id for item in self.exercises]
        if len(ids) != len(set(ids)):
            raise ValueError("Each assigned exercise can appear only once")
        return self


class MemberWorkoutSessionResponse(ApiModel):
    id: UUID
    session_date: date
    status: Literal["in_progress", "completed"]
    exercises: list[MemberWorkoutExerciseLog]
    recorded_at: datetime
    completed_at: datetime | None


class MemberWorkoutResponse(ApiModel):
    id: UUID
    program_id: UUID
    program_name: str
    goal: str
    description: str | None
    starts_on: date
    status: Literal["assigned", "in_progress", "completed"]
    notes: str | None
    recommended_days_per_week: int
    expected_session_minutes: int
    exercises: list[MemberWorkoutExercise]
    sessions: list[MemberWorkoutSessionResponse]


class MemberEventResponse(EventResponse):
    registration_status: Literal["confirmed", "cancelled"] | None = None


class MemberProgressResponse(ApiModel):
    assessments: list[FitnessAssessmentHistoryItem]
    check_ins_this_month: int
    workouts_this_month: int
