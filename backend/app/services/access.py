from __future__ import annotations

from datetime import datetime

from backend.app.models.member import Member
from backend.app.models.membership import MembershipPlan, PlanAccessWindow, Subscription
from backend.app.schemas.operations import AttendanceRestriction


def evaluate_access(
    member: Member,
    subscription: Subscription | None,
    plan: MembershipPlan | None,
    windows: list[PlanAccessWindow],
    checked_at: datetime,
    duplicate_check_in_at: datetime | None = None,
) -> list[AttendanceRestriction]:
    """Return the restrictions that staff must resolve before a check-in."""
    restrictions: list[AttendanceRestriction] = []
    local_day = checked_at.date()

    if member.status != "active":
        restrictions.append(
            AttendanceRestriction(
                code="member_inactive",
                message="This member account is inactive.",
                override_allowed=True,
            )
        )

    if subscription is None or subscription.status == "cancelled":
        restrictions.append(
            AttendanceRestriction(
                code="no_subscription",
                message="There is no current membership subscription.",
                override_allowed=True,
            )
        )
    elif subscription.starts_on > local_day:
        restrictions.append(
            AttendanceRestriction(
                code="no_subscription",
                message="The next subscription has not started yet.",
                override_allowed=True,
            )
        )
    elif subscription.expires_on < local_day:
        restrictions.append(
            AttendanceRestriction(
                code="expired",
                message=f"This membership expired on {subscription.expires_on.isoformat()}.",
                override_allowed=True,
            )
        )
    elif plan is None or not plan.is_active:
        restrictions.append(
            AttendanceRestriction(
                code="plan_inactive",
                message="The member's plan is not active for new visits.",
                override_allowed=True,
            )
        )
    elif not any(
        window.weekday == checked_at.weekday()
        and window.starts_at <= checked_at.time().replace(tzinfo=None) < window.ends_at
        for window in windows
    ):
        restrictions.append(
            AttendanceRestriction(
                code="outside_hours",
                message="This visit is outside the access hours for the member's plan.",
                override_allowed=True,
            )
        )

    if duplicate_check_in_at is not None:
        restrictions.append(
            AttendanceRestriction(
                code="duplicate",
                message="A recent check-in already exists within the duplicate interval.",
                override_allowed=False,
            )
        )

    return restrictions
