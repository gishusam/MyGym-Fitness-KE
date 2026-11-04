from backend.app.models.fitness_assessment import FitnessAssessment
from backend.app.schemas.operations import FitnessAssessmentInput
from uuid import UUID
from pydantic import ValidationError
import pytest
from sqlalchemy import select


def test_assessment_requires_a_measurement():
    with pytest.raises(ValidationError):
        FitnessAssessmentInput()


def test_out_of_range_percentage_rejected():
    with pytest.raises(ValidationError):
        FitnessAssessmentInput(bodyFatPercent=105)


def test_member_registration_persists_initial_assessment(client, db):
    res = client.post('/api/members', json={
        'fullName':'Fitness Test Member', 'phone':'0712345678',
        'initialAssessment': {'weightKg': 72, 'heightCm': 180, 'bodyFatPercent': 18.4, 'musclePercent': 42, 'visceralFatLevel': 8}
    })
    assert res.status_code == 201, res.text
    data = res.json()
    assert data['latestAssessment']['bmi'] == 22.2
    member_id = data['id']
    history = db.scalars(select(FitnessAssessment).where(FitnessAssessment.member_id == UUID(member_id))).all()
    assert len(history) == 1
    assert history[0].weight_kg == 72


def test_member_without_measurements_is_still_allowed(client, db):
    res = client.post('/api/members', json={'fullName':'No Measurements Member', 'phone':'0712345679'})
    assert res.status_code == 201, res.text
    assert res.json()['latestAssessment'] is None
