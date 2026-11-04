from backend.app.models.fitness_assessment import FitnessAssessment
from sqlalchemy import select, func


def test_fitness_assessment_history_and_bmi(client, db):
    new = client.post('/api/members', json={
        'fullName':'Fitness Test Member','phone':'0712345678',
        'initialAssessment':{'weightKg':82,'heightCm':180}
    })
    assert new.status_code == 201, new.text
    member_id=new.json()['id']
    created=client.post(f'/api/members/{member_id}/fitness-assessments',json={
        'weightKg':78,'heightCm':180,'bodyFatPercent':19.5
    })
    assert created.status_code == 201, created.text
    assert created.json()['bmi'] == 24.1
    response=client.get(f'/api/members/{member_id}/fitness-assessments')
    assert response.status_code == 200
    assert len(response.json()['items'])==2
    assert [r['weightKg'] for r in response.json()['items']]==[78.0,82.0]
    assert db.scalar(select(func.count()).select_from(FitnessAssessment))==2


def test_fitness_assessment_validation_and_missing_member(client):
    response=client.post('/api/members/00000000-0000-0000-0000-000000000001/fitness-assessments',json={'weightKg':70})
    assert response.status_code==404
    created=client.post('/api/members',json={'fullName':'Another Test Member','phone':'0712345679'})
    assert created.status_code==201
    member_id=created.json()['id']
    for invalid in ({},{'weightKg':0},{'heightCm':301},{'bodyFatPercent':105}):
        result=client.post(f'/api/members/{member_id}/fitness-assessments',json=invalid)
        assert result.status_code==422, result.text
