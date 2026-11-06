from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID as PyUUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.auth import get_current_staff
from backend.app.main import app
from backend.app.models.member_onboarding import (
    MemberFitnessProfile,
    MemberOnboardingToken,
)
from backend.app.models.workout import WorkoutAssignment
from backend.app.models import StaffRole, StaffUser


def create_member(client, phone: str, name: str) -> dict:
    response = client.post("/api/members", json={"fullName": name, "phone": phone})
    assert response.status_code == 201, response.text
    return response.json()


def create_program(
    client,
    name: str,
    *,
    goal: str = "Build steady full-body strength",
    days: int = 3,
    duration: int = 45,
    equipment: list[str] | None = None,
    supported_goals: list[str] | None = None,
    min_experience: str = "beginner",
    max_experience: str = "advanced",
    requires_review: bool = False,
) -> dict:
    response = client.post(
        "/api/workouts",
        json={
            "name": name,
            "goal": goal,
            "description": "A trainer-created program using the exercises below.",
            "goalsSupported": supported_goals or ["build_strength"],
            "minimumExperience": min_experience,
            "maximumExperience": max_experience,
            "recommendedDaysPerWeek": days,
            "expectedSessionMinutes": duration,
            "equipmentRequirements": equipment or [],
            "trainerReviewRequired": requires_review,
            "exercises": [
                {
                    "name": "Goblet squat",
                    "sets": 3,
                    "repetitions": 10,
                    "restSeconds": 60,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def questionnaire(**changes) -> dict:
    values = {
        "primaryGoal": "build_strength",
        "experience": "beginner",
        "availableDaysPerWeek": 3,
        "sessionDurationMinutes": 60,
        "equipmentPreferences": ["dumbbells"],
        "limitations": None,
        "notes": "I am new to training.",
    }
    values.update(changes)
    return values


def test_public_onboarding_recommends_only_saved_matching_program(
    client, db: Session
) -> None:
    member = create_member(client, "0712345681", "Amina Otieno")
    program = create_program(client, "Strength Foundations")

    app.dependency_overrides.pop(get_current_staff, None)
    response = client.post(
        f"/api/public/onboarding/{member['onboardingToken']}",
        json=questionnaire(),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["firstName"] == "Amina"
    assert result["submitted"] is True
    assert result["reviewStatus"] == "awaiting_review"
    assert result["recommendation"]["id"] == program["id"]
    assert result["recommendation"]["exercises"][0]["name"] == "Goblet squat"
    assert "Supports your selected goal." in result["recommendation"]["matchReasons"]
    assert result["assignedProgram"] is None
    assert not db.scalars(select(WorkoutAssignment)).all()

    token_row = db.scalar(select(MemberOnboardingToken))
    assert token_row is not None
    assert token_row.token_hash != member["onboardingToken"]
    assert len(token_row.token_hash) == 64
    profile = db.scalar(select(MemberFitnessProfile))
    assert profile is not None
    assert str(profile.recommended_program_id) == program["id"]


def test_questionnaire_resumes_and_no_match_is_sent_to_trainer(
    client, staff_factory
) -> None:
    member = create_member(client, "0712345682", "Brian Njoroge")
    create_program(client, "Strength Foundations")
    first = client.post(
        f"/api/public/onboarding/{member['onboardingToken']}",
        json=questionnaire(limitations="My knee is recovering from an injury."),
    )
    assert first.status_code == 200, first.text
    assert first.json()["recommendation"] is None
    assert "trainer will review" in first.json()["noMatchReason"].lower()

    resumed = client.get(f"/api/public/onboarding/{member['onboardingToken']}")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["questionnaire"]["limitations"] == (
        "My knee is recovering from an injury."
    )
    assert resumed.json()["recommendation"] is None

    staff = staff_factory(StaffRole.TRAINER)
    app.dependency_overrides[get_current_staff] = lambda: staff
    queue = client.get("/api/onboarding/reviews")
    assert queue.status_code == 200, queue.text
    assert len(queue.json()) == 1
    assert queue.json()[0]["memberId"] == member["id"]
    assert queue.json()[0]["recommendation"] is None


def test_match_excludes_programs_that_do_not_fit_experience_days_time_or_equipment(
    client,
) -> None:
    member = create_member(client, "0712345683", "Neema Wanjiku")
    correct = create_program(client, "Beginner Plan", days=2, duration=45)
    create_program(
        client,
        "Advanced Plan",
        min_experience="advanced",
        max_experience="advanced",
    )
    create_program(client, "Five Day Plan", days=5)
    create_program(client, "Barbell Plan", equipment=["barbell"])
    create_program(client, "Long Session Plan", duration=90)
    create_program(
        client,
        "Weight Loss Plan",
        supported_goals=["lose_weight"],
    )

    response = client.post(
        f"/api/public/onboarding/{member['onboardingToken']}",
        json=questionnaire(availableDaysPerWeek=3, sessionDurationMinutes=60),
    )
    assert response.status_code == 200, response.text
    assert response.json()["recommendation"]["id"] == correct["id"]
    assert response.json()["alternatives"] == []


def test_advanced_member_gets_an_advanced_saved_program(client) -> None:
    member = create_member(client, "0712345687", "Kevin Mwangi")
    create_program(client, "Beginner Only", max_experience="beginner")
    advanced = create_program(
        client,
        "Advanced Strength Cycle",
        min_experience="advanced",
        max_experience="advanced",
    )

    response = client.post(
        f"/api/public/onboarding/{member['onboardingToken']}",
        json=questionnaire(experience="advanced"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["recommendation"]["id"] == advanced["id"]


def test_recommendations_are_member_scoped(client) -> None:
    first = create_member(client, "0712345688", "Njeri Kamau")
    second = create_member(client, "0712345689", "David Muriuki")
    create_program(client, "Strength Foundations")
    submission = client.post(
        f"/api/public/onboarding/{first['onboardingToken']}",
        json=questionnaire(notes="Private note for Njeri"),
    )
    assert submission.status_code == 200, submission.text

    other_member_view = client.get(
        f"/api/public/onboarding/{second['onboardingToken']}"
    )
    assert other_member_view.status_code == 200, other_member_view.text
    assert other_member_view.json()["firstName"] == "David"
    assert other_member_view.json()["questionnaire"] is None
    assert "Private note for Njeri" not in other_member_view.text


def test_trainer_can_change_suggestion_and_assign_final_program(
    client, staff_factory, db: Session
) -> None:
    member = create_member(client, "0712345684", "Otieno Kamau")
    recommended = create_program(client, "Suggested Strength")
    alternate = create_program(client, "Trainer Selected Strength", days=2)
    submitted = client.post(
        f"/api/public/onboarding/{member['onboardingToken']}",
        json=questionnaire(),
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["recommendation"]["id"] == recommended["id"]

    trainer: StaffUser = staff_factory(StaffRole.TRAINER)
    app.dependency_overrides[get_current_staff] = lambda: trainer
    assigned = client.post(
        f"/api/onboarding/reviews/{member['id']}/assign",
        json={
            "programId": alternate["id"],
            "startsOn": date.today().isoformat(),
            "notes": "Reviewed the goal and chosen schedule.",
        },
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["programId"] == alternate["id"]
    assert assigned.json()["status"] == "assigned"
    assert db.scalar(select(WorkoutAssignment).where(
        WorkoutAssignment.member_id == PyUUID(member["id"])
    )) is not None

    public_view = client.get(f"/api/public/onboarding/{member['onboardingToken']}")
    assert public_view.status_code == 200, public_view.text
    assert public_view.json()["reviewStatus"] == "trainer_approved"
    assert public_view.json()["assignedProgram"]["id"] == alternate["id"]
    assert public_view.json()["recommendation"]["id"] == recommended["id"]
    assert client.get("/api/onboarding/reviews").json() == []


def test_reissuing_revokes_old_token_and_expired_links_are_unavailable(
    client, db: Session
) -> None:
    member = create_member(client, "0712345685", "Wairimu Maina")
    previous = member["onboardingToken"]
    response = client.post(f"/api/members/{member['id']}/onboarding-link")
    assert response.status_code == 201, response.text
    fresh = response.json()["token"]
    assert fresh != previous
    assert client.get(f"/api/public/onboarding/{previous}").status_code == 404
    assert client.get(f"/api/public/onboarding/{fresh}").status_code == 200

    assert len(db.scalars(select(MemberOnboardingToken)).all()) == 2
    active = db.scalar(
        select(MemberOnboardingToken).where(MemberOnboardingToken.revoked_at.is_(None))
    )
    assert active is not None
    active.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/public/onboarding/{fresh}").status_code == 404


def test_staff_can_explicitly_revoke_member_onboarding_link(client) -> None:
    member = create_member(client, "0712345686", "Linet Wambui")
    token = member["onboardingToken"]
    revoked = client.post(f"/api/members/{member['id']}/onboarding-link/revoke")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"revoked": True}
    assert client.get(f"/api/public/onboarding/{token}").status_code == 404
    assert client.post(
        f"/api/members/{member['id']}/onboarding-link/revoke"
    ).json() == {"revoked": False}


def test_receptionist_cannot_access_trainer_review_queue(
    client, staff_factory
) -> None:
    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    app.dependency_overrides[get_current_staff] = lambda: receptionist
    assert client.get("/api/onboarding/reviews").status_code == 403
