from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.app.core.auth import get_current_staff
from backend.app.main import app
from backend.app.models.member_workout_link import MemberWorkoutLink
from backend.app.models.membership import MembershipPlan, Subscription
from backend.app.models import StaffRole


def test_workout_link_is_scoped_revocable_and_downloads_pdf(client, db, staff_factory):
    member = client.post('/api/members', json={'fullName':'Jane Example','phone':'0712345670'})
    assert member.status_code == 201, member.text
    member_id = member.json()['id']
    today = datetime.now(ZoneInfo('Africa/Nairobi')).date()
    plan_id = uuid4()
    db.add(MembershipPlan(id=plan_id, name='Test Gym Access', monthly_price_kes=4000, is_active=True))
    db.add(Subscription(id=uuid4(), member_id=UUID(member_id), plan_id=plan_id, plan_name='Test Gym Access', monthly_price_kes=4000,
                        starts_on=today-timedelta(days=1), expires_on=today+timedelta(days=29), status='active'))
    db.commit()
    program = client.post('/api/workouts', json={
        'name':'Beginner Foundation', 'goal':'Build strength', 'goalsSupported':['build_strength'],
        'minimumExperience':'beginner','maximumExperience':'advanced','recommendedDaysPerWeek':3,'expectedSessionMinutes':45,
        'exercises':[{'name':'Goblet squat','sets':3,'repetitions':10,'restSeconds':60}],
    })
    assert program.status_code == 201, program.text
    assigned = client.post(f"/api/workouts/{program.json()['id']}/assignments", json={'memberId':member_id,'startsOn':today.isoformat()})
    assert assigned.status_code == 201, assigned.text
    assignment_id = assigned.json()['id']
    share = client.post(f'/api/workout-assignments/{assignment_id}/share-link')
    assert share.status_code == 200, share.text
    token = share.json()['token']
    row = db.scalar(select(MemberWorkoutLink))
    assert row and row.token_hash != token and len(row.token_hash) == 64
    public = client.get(f'/api/public/workout/{token}')
    assert public.status_code == 200, public.text
    assert public.json()['memberName'] == 'Jane Example'
    assert public.json()['exercises'][0]['name'] == 'Goblet squat'
    pdf = client.get(f'/api/public/workout/{token}/pdf')
    assert pdf.status_code == 200, pdf.text[:200] if pdf.status_code!=200 else ''
    assert pdf.content.startswith(b'%PDF-')
    assert pdf.headers['content-type'].startswith('application/pdf')

    new_share = client.post(f'/api/workout-assignments/{assignment_id}/share-link')
    assert new_share.status_code == 200
    assert client.get(f'/api/public/workout/{token}').status_code == 404
    token2 = new_share.json()['token']
    assert client.get(f'/api/public/workout/{token2}').status_code == 200
    assert client.post(f'/api/workout-assignments/{assignment_id}/share-link/revoke').json()['revoked'] is True
    assert client.get(f'/api/public/workout/{token2}/pdf').status_code == 404

    receptionist = staff_factory(StaffRole.RECEPTIONIST)
    app.dependency_overrides[get_current_staff] = lambda: receptionist
    assert client.post(f'/api/workout-assignments/{assignment_id}/share-link').status_code == 403
