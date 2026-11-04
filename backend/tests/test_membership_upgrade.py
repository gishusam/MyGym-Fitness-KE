from uuid import uuid4
from datetime import date, timedelta
from sqlalchemy import select
from backend.app.models.membership import MembershipPlan, PlanAccessWindow, Subscription
from backend.app.models.membership_upgrade import MembershipUpgrade
from backend.app.models.payment import Payment
from backend.app.models.audit_log import AuditLog


def test_upgrade_is_atomic_and_audited(client, db):
    member = client.post('/api/members', json={'fullName':'Upgrade Test','phone':'0712345678'})
    assert member.status_code == 201, member.text
    mid=member.json()['id']
    start=date.today().isoformat()
    # Local date may differ at midnight in another timezone; use Kenya date.
    from zoneinfo import ZoneInfo
    from datetime import datetime
    start=datetime.now(ZoneInfo('Africa/Nairobi')).date().isoformat()
    off_response=client.post('/api/membership-plans',json={'name':'Off-Peak','monthlyPriceKes':4000,'isActive':True,'accessWindows':[{'weekday':n,'startsAt':'09:00','endsAt':'15:00'} for n in range(7)]})
    assert off_response.status_code==201,off_response.text
    off=off_response.json()
    first=client.post(f'/api/members/{mid}/subscriptions',json={'planId':off['id'],'startsOn':start})
    assert first.status_code == 201, first.text
    sid=first.json()['id']; expiry=first.json()['expiresOn']
    peak=MembershipPlan(id=uuid4(), name='Test Full Access', monthly_price_kes=5000, is_active=True)
    db.add(peak); db.flush()
    for n in range(7):db.add(PlanAccessWindow(plan_id=peak.id, weekday=n, starts_at=__import__('datetime').time(0,0), ends_at=__import__('datetime').time(23,59)))
    db.commit()
    body={'toPlanId':str(peak.id),'method':'mpesa_manual','reference':'TEST-TOPUP-123'}
    result=client.post(f'/api/members/{mid}/subscriptions/{sid}/upgrade',json=body)
    assert result.status_code == 201, result.text
    assert result.json()['topupKes']==1000
    subscription=db.get(Subscription,__import__('uuid').UUID(sid))
    db.refresh(subscription)
    assert subscription.expires_on.isoformat()==expiry
    assert subscription.plan_id==peak.id
    upgrade=db.scalar(select(MembershipUpgrade).where(MembershipUpgrade.subscription_id==subscription.id))
    assert upgrade.from_plan_name=='Off-Peak'
    payment=db.get(Payment,upgrade.payment_id)
    assert payment.amount_kes==1000 and payment.reference=='TEST-TOPUP-123'
    assert db.scalar(select(AuditLog).where(AuditLog.action=='membership_upgraded')) is not None
    again=client.post(f'/api/members/{mid}/subscriptions/{sid}/upgrade',json=body)
    assert again.status_code==409
    assert db.query(Payment).filter(Payment.reference=='TEST-TOPUP-123').count()==1


def test_upgrade_rejects_inactive_target(client):
    member=client.post('/api/members',json={'fullName':'Second Member','phone':'0712345678'}).json()
    from zoneinfo import ZoneInfo
    from datetime import datetime
    off=client.post('/api/membership-plans',json={'name':'Off-Peak','monthlyPriceKes':4000,'isActive':True,'accessWindows':[{'weekday':n,'startsAt':'09:00','endsAt':'15:00'} for n in range(7)]}).json()
    peak=client.post('/api/membership-plans',json={'name':'Peak Access','monthlyPriceKes':5000,'isActive':False,'accessWindows':[]}).json()
    sub=client.post(f"/api/members/{member['id']}/subscriptions",json={'planId':off['id'],'startsOn':datetime.now(ZoneInfo('Africa/Nairobi')).date().isoformat()}).json()
    r=client.post(f"/api/members/{member['id']}/subscriptions/{sub['id']}/upgrade",json={'toPlanId':peak['id'],'method':'mpesa_manual','reference':'TEST-INACTIVE-001'})
    assert r.status_code==422
