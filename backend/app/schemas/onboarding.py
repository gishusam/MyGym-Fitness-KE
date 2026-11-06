from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from backend.app.schemas.base import ApiModel
from backend.app.schemas.workspaces import WorkoutExerciseResponse


FitnessGoal = Literal[
    "build_strength",
    "lose_weight",
    "improve_fitness",
    "gain_muscle",
    "general_wellness",
]
ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
EquipmentOption = Literal[
    "bodyweight",
    "dumbbells",
    "resistance_bands",
    "barbell",
    "machines",
    "cardio_machines",
    "full_gym",
]


class MemberOnboardingInput(ApiModel):
    primary_goal: FitnessGoal
    experience: ExperienceLevel
    available_days_per_week: int = Field(ge=1, le=7)
    session_duration_minutes: int = Field(ge=15, le=180)
    equipment_preferences: list[EquipmentOption] = Field(default_factory=list, max_length=7)
    limitations: str | None = Field(default=None, max_length=1200)
    notes: str | None = Field(default=None, max_length=1200)

    @field_validator("limitations", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()) or None


class OnboardingLinkResponse(ApiModel):
    token: str
    expires_at: datetime


class OnboardingRevocationResponse(ApiModel):
    revoked: bool


class OnboardingProgram(ApiModel):
    id: UUID
    name: str
    goal: str
    description: str | None
    recommended_days_per_week: int
    expected_session_minutes: int
    equipment_requirements: list[str]
    trainer_review_required: bool
    exercises: list[WorkoutExerciseResponse]
    match_reasons: list[str] = Field(default_factory=list)


class MemberOnboardingView(ApiModel):
    first_name: str
    expires_at: datetime
    submitted: bool
    questionnaire: MemberOnboardingInput | None = None
    review_status: Literal["awaiting_review", "trainer_approved"] | None = None
    recommendation: OnboardingProgram | None = None
    alternatives: list[OnboardingProgram] = Field(default_factory=list)
    no_match_reason: str | None = None
    assigned_program: OnboardingProgram | None = None


class OnboardingReviewItem(ApiModel):
    member_id: UUID
    member_name: str
    member_number: str
    primary_goal: FitnessGoal
    experience: ExperienceLevel
    available_days_per_week: int
    session_duration_minutes: int
    equipment_preferences: list[str]
    limitations: str | None
    notes: str | None
    recommendation: OnboardingProgram | None
    alternatives: list[OnboardingProgram]
    submitted_at: datetime


class OnboardingAssignmentInput(ApiModel):
    program_id: UUID
    starts_on: date
    notes: str | None = Field(default=None, max_length=1000)
