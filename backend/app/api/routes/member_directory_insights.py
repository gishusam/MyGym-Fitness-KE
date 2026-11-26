"""Read-only metrics for the MyGym Members directory.

Membership status is determined by date and excludes cancelled subscriptions.
No sample numbers, cross-tenant joins, or member photos are used.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.auth import require_owner_or_receptionist
from backend.app.db.session import get_db
from backend.app.models.attendance import CheckIn
from backend.app.models.member import Member, MemberStatus
from backend.app.models.membership import MembershipPlan, Subscription, SubscriptionStatus
from backend.app.models.staff_user import StaffUser
from backend.app.services.operations import gym_now, local_day_bounds

router = APIRouter(tags=["members"])


@router.get("/members/directory-insights", operation_id="getMemberDirectoryInsights")
def member_directory_insights(
    member_ids: str | None = Query(default=None, alias="memberIds", max_length=6000),
    _staff: StaffUser = Depends(require_owner_or_receptionist),
    session: Session = Depends(get_db),
) -> dict:
    now = gym_now(session)
    today = now.date()
    month_start = today.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    month_start_utc, _ = local_day_bounds(month_start, now.tzinfo)
    previous_start_utc, _ = local_day_bounds(previous_month_start, now.tzinfo)
    today_start_utc, tomorrow_start_utc = local_day_bounds(today, now.tzinfo)
    last_30_utc = (now - timedelta(days=30)).astimezone(timezone.utc)

    total = session.scalar(select(func.count()).select_from(Member)) or 0
    new_month = session.scalar(
        select(func.count()).select_from(Member).where(Member.registered_at >= month_start_utc)
    ) or 0
    previous_month = session.scalar(
        select(func.count()).select_from(Member).where(
            Member.registered_at >= previous_start_utc,
            Member.registered_at < month_start_utc,
        )) or 0
    checkins_today = session.scalar(
        select(func.count()).select_from(CheckIn).where(
            CheckIn.checked_in_at >= today_start_utc,
            CheckIn.checked_in_at < tomorrow_start_utc,
        )) or 0
    engaged = session.scalar(
        select(func.count(func.distinct(CheckIn.member_id))).where(
            CheckIn.checked_in_at >= last_30_utc
        )
    ) or 0

    # Prefer an active subscription covering today; otherwise use the most
    # recent non-cancelled subscription for expiry/status display.
    subscriptions = session.scalars(
        select(Subscription).where(Subscription.status != SubscriptionStatus.CANCELLED.value)
        .order_by(Subscription.starts_on.desc(), Subscription.created_at.desc())
    ).all()
    latest_by_member = {}
    current_by_member = {}
    for sub in subscriptions:
        latest_by_member.setdefault(sub.member_id, sub)
        if sub.starts_on <= today <= sub.expires_on:
            current_by_member.setdefault(sub.member_id, sub)

    plans = list(session.scalars(select(MembershipPlan).order_by(MembershipPlan.name)))
    distribution = Counter(s.plan_id for s in current_by_member.values())
    active_count = len(current_by_member)
    plan_cards = [
        {"id": str(p.id), "name": p.name, "count": distribution[p.id],
         "percentage": round(distribution[p.id] / active_count * 100) if active_count else 0}
        for p in plans
    ]
    # Display a true unassigned segment rather than inventing a membership plan.
    plan_cards.append({"id": "unassigned", "name": "No current plan",
                       "count": max(0, total - active_count),
                       "percentage": round((total - active_count) / total * 100) if total else 0})
    renewals_due = sum(1 for s in current_by_member.values()
                       if 0 <= (s.expires_on - today).days <= 7)

    requested = []
    for raw in (member_ids or "").split(","):
        if not raw.strip():
            continue
        try:
            requested.append(UUID(raw.strip()))
        except ValueError:
            continue
    requested = list(dict.fromkeys(requested))[:100]
    last_visits = {}
    visit_counts = {}
    if requested:
        last_visits = dict(session.execute(
            select(CheckIn.member_id, func.max(CheckIn.checked_in_at))
            .where(CheckIn.member_id.in_(requested)).group_by(CheckIn.member_id)
        ).all())
        visit_counts = dict(session.execute(
            select(CheckIn.member_id, func.count())
            .where(CheckIn.member_id.in_(requested), CheckIn.checked_in_at >= last_30_utc)
            .group_by(CheckIn.member_id)
        ).all())
    page_member_rows = []
    if requested:
        page_member_rows = session.execute(
            select(Member.id, Member.status).where(Member.id.in_(requested))
        ).all()
    details = {}
    for member_id, member_status in page_member_rows:
        current = current_by_member.get(member_id)
        latest = current or latest_by_member.get(member_id)
        if member_status != MemberStatus.ACTIVE.value:
            status = "inactive"
        elif current is not None:
            status = "expiring" if (current.expires_on - today).days <= 7 else "active"
        elif latest and latest.expires_on < today:
            status = "expired"
        else:
            status = "no_plan"
        visit = last_visits.get(member_id)
        details[str(member_id)] = {
            "planName": latest.plan_name if latest else None,
            "expiresOn": latest.expires_on.isoformat() if latest else None,
            "subscriptionStatus": status,
            "lastCheckIn": visit.isoformat() if visit else None,
            "visits30d": visit_counts.get(member_id, 0),
        }

    return {
        "totalMembers": total,
        "activeSubscriptions": active_count,
        "visitors30d": engaged,
        "newThisMonth": new_month,
        "newPreviousMonth": previous_month,
        "checkInsToday": checkins_today,
        "renewalsDue": renewals_due,
        "planDistribution": plan_cards,
        "memberDetails": details,
    }
