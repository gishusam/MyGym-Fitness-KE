"""Owner-only, explainable member follow-ups. No speculative AI churn score."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner
from backend.app.db.session import get_db
from backend.app.models.attendance import CheckIn
from backend.app.models.member import Member
from backend.app.models.membership import Subscription
from backend.app.models.staff_user import StaffUser
from backend.app.services.operations import gym_now

router = APIRouter(tags=['member retention'])

@router.get('/dashboard/retention', operation_id='getMemberRetentionSignals')
def retention_signals(
    _owner: StaffUser = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    today = gym_now(db).date()
    cutoff = datetime.combine(today - timedelta(days=56), time.min, tzinfo=ZoneInfo('Africa/Nairobi')).astimezone(timezone.utc)
    members = db.scalars(select(Member).where(Member.status == 'active').order_by(Member.full_name)).all()
    if not members:
        return {'atRiskCount': 0, 'inactiveCount': 0, 'expiringCount': 0, 'signals': []}
    ids = [m.id for m in members]
    subscriptions = db.scalars(select(Subscription).where(
        Subscription.member_id.in_(ids), Subscription.status != 'cancelled',
        Subscription.starts_on <= today, Subscription.expires_on >= today)).all()
    current = {s.member_id: s for s in subscriptions}
    checkins = db.scalars(select(CheckIn).where(CheckIn.member_id.in_(ids), CheckIn.checked_in_at >= cutoff)).all()
    by_member = {m.id: [] for m in members}
    for c in checkins:
        dt = c.checked_in_at.replace(tzinfo=timezone.utc) if c.checked_in_at.tzinfo is None else c.checked_in_at
        by_member[c.member_id].append(dt.astimezone(ZoneInfo('Africa/Nairobi')).date())
    items = []
    inactive_count = expiring_count = declining_count = 0
    for member in members:
        sub = current.get(member.id)
        if not sub:
            continue  # expired members belong in existing renewal workflows
        visits = by_member[member.id]
        member_signals = []
        remaining = (sub.expires_on - today).days
        if remaining <= 7:
            expiring_count += 1
            member_signals.append({'code': 'renewal_due', 'label': 'Renewal due', 'detail': f'Membership expires in {remaining} day(s).'})
        # Avoid flagging brand-new members who have not had time to attend.
        registered = member.registered_at.replace(tzinfo=timezone.utc) if member.registered_at.tzinfo is None else member.registered_at
        age_days = (today - registered.astimezone(ZoneInfo('Africa/Nairobi')).date()).days
        if age_days >= 14:
            recent = sum(today - timedelta(days=14) < v <= today for v in visits)
            baseline = sum(today - timedelta(days=42) < v <= today - timedelta(days=14) for v in visits)
            if not visits or max(visits) < today-timedelta(days=14):
                inactive_count += 1
                member_signals.append({'code': 'inactive_visits', 'label': 'Inactivity', 'detail': 'No check-ins in the past 14 days.'})
            elif baseline >= 4 and recent * 2 <= baseline // 2:
                declining_count += 1
                member_signals.append({'code': 'declining_visits', 'label': 'Declining visits', 'detail': f'{recent} visits in 14 days versus {baseline} in prior 28 days.'})
        if member_signals:
            items.append({'memberId': str(member.id), 'memberNumber': member.member_number,
                          'name': member.full_name, 'phone': member.phone,
                          'signals': member_signals})
    items.sort(key=lambda row: (0 if any(s['code']=='renewal_due' for s in row['signals']) else 1, row['name']))
    return {'atRiskCount': declining_count, 'inactiveCount': inactive_count,
            'expiringCount': expiring_count, 'signals': items[:30]}
