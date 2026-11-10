"""Seed a SEPARATE MyGym demo database with 25 fictional members.

Never run against the real gym database. Requires MYGYM_DEMO_MODE=1 and a database
whose name includes 'demo'. Run normal Alembic migrations and owner bootstrap first.
Seed is deliberately non-destructive: it refuses a nonempty members table.
"""
from __future__ import annotations

import argparse
import os
import secrets
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from backend.app.db.session import get_engine, get_session_factory
from backend.app.models.attendance import CheckIn
from backend.app.models.gym_event import EventRegistration, GymEvent
from backend.app.models.gym_settings import GymSettings
from backend.app.models.member import Member
from backend.app.models.member_onboarding import MemberFitnessProfile
from backend.app.models.membership import MembershipPlan, PlanAccessWindow, Subscription
from backend.app.models.payment import Payment
from backend.app.models.workout import WorkoutAssignment, WorkoutExercise, WorkoutProgram

NAMES = [
    "Amina Otieno", "Brian Mwangi", "Grace Wanjiku", "David Kamau", "Faith Njeri",
    "Kevin Ochieng", "Neema Mutiso", "Peter Kiptoo", "Sharon Achieng", "Mercy Wambui",
    "Daniel Karanja", "Linet Muthoni", "Abdi Hassan", "Eunice Nyambura", "James Odhiambo",
    "Alice Wairimu", "Dennis Maina", "Joyce Mumbi", "Joseph Musyoka", "Cynthia Atieno",
    "Victor Kimani", "Mary Chebet", "George Kariuki", "Esther Moraa", "Ian Njoroge",
]
DEMO_ID_PREFIX = 'MG-DEMO-'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='Actually insert demo records')
    args = ap.parse_args()
    engine = get_engine()
    dbname = engine.url.database or ''
    if os.getenv('MYGYM_DEMO_MODE') != '1' or 'demo' not in dbname.lower():
        raise SystemExit('REFUSED: Set MYGYM_DEMO_MODE=1 and use a database name containing demo.')
    with engine.connect() as conn:
        before = conn.scalar(select(func.count()).select_from(Member))
        if before:
            raise SystemExit(f'REFUSED: members already exist ({before}). Use a fresh dedicated demo database.')
    if not args.apply:
        print(f'DRY RUN: would seed 25 members in database {dbname!r}. Pass --apply to write.')
        return

    today = datetime.now(ZoneInfo('Africa/Nairobi')).date()
    utcnow = datetime.now(timezone.utc)
    with get_session_factory()() as db:
        settings = db.get(GymSettings, 1)
        if not settings:
            raise SystemExit('Initialize MyGym and bootstrap the owner before seeding the demo.')
        settings.gym_name = 'DemoFit Studio · DEMO DATA'
        settings.renewal_reminder_days_before = 7
        settings.inactivity_threshold_days = 14
        plans = []
        for title, price in [('Off-Peak', 4000), ('Peak Access', 5000)]:
            plan = db.scalar(select(MembershipPlan).where(MembershipPlan.name == title))
            if plan is None:
                plan = MembershipPlan(id=uuid4(), name=title, monthly_price_kes=price, is_active=True)
                db.add(plan)
                db.flush()
            else:
                plan.is_active = True
            plans.append(plan)
            for day in range(7):
                exists = db.scalar(select(PlanAccessWindow).where(PlanAccessWindow.plan_id == plan.id, PlanAccessWindow.weekday == day))
                if exists is None:
                    db.add(PlanAccessWindow(plan_id=plan.id, weekday=day, starts_at=time(9 if price == 4000 else 5, 0), ends_at=time(15 if price == 4000 else 22, 0)))

        programs = []
        for name, goal, category, days in [
            ('Strength Foundations', 'Build steady strength', 'build_strength', 3),
            ('Fitness Starter', 'Improve overall fitness', 'improve_fitness', 2),
            ('Body Composition', 'Lose fat and build consistency', 'lose_weight', 4),
        ]:
            program = WorkoutProgram(id=uuid4(), name=name, goal=goal, status='active',
                description='Demo trainer-designed exercise routine. Ask a coach to adjust your plan.',
                goals_supported=[category], minimum_experience='beginner', maximum_experience='advanced',
                recommended_days_per_week=days, expected_session_minutes=45,
                equipment_requirements=['dumbbells'], trainer_review_required=True)
            db.add(program)
            db.flush()
            programs.append(program)
            for pos, exercise in enumerate(['Bodyweight squat', 'Seated row', 'Incline press']):
                db.add(WorkoutExercise(id=uuid4(), program_id=program.id, position=pos, name=exercise,
                    sets=3, repetitions=10, rest_seconds=60))

        people = []
        for i, name in enumerate(NAMES):
            # Reserved fictional range; do not send messages to demo phone numbers.
            member = Member(id=uuid4(), member_number=f'{DEMO_ID_PREFIX}{i+1:03d}', full_name=name,
                phone=f'+254700000{i+1:03d}', status='inactive' if i in (22,23,24) else 'active',
                qr_token=secrets.token_urlsafe(32), registered_at=utcnow-timedelta(days=185-i*4))
            db.add(member)
            people.append(member)
        db.flush()

        for i, member in enumerate(people):
            plan = plans[i % 2]
            # 0-17 have current terms, some due soon; 18-19 upcoming;
            # 20-21 expired; 22-24 inactive/expired. These groups are exclusive.
            if i < 18:
                remaining = [1, 2, 4, 6, 9, 12, 15, 20][i % 8]
                expiry = today + timedelta(days=remaining)
                starts = expiry-timedelta(days=29)
                status = 'active'
            elif i < 20:
                starts = today + timedelta(days=i-17)
                expiry = starts + timedelta(days=29)
                status = 'scheduled'
            else:
                expiry = today-timedelta(days=i-17)
                starts = expiry-timedelta(days=29)
                status = 'active'  # expiration is determined by the dates
            sub = Subscription(id=uuid4(), member_id=member.id, plan_id=plan.id,
                plan_name=plan.name, monthly_price_kes=plan.monthly_price_kes,
                starts_on=starts, expires_on=expiry, status=status)
            db.add(sub)
            if i not in (18, 19, 24):
                db.add(Payment(id=uuid4(), member_id=member.id, subscription_id=sub.id,
                    amount_kes=plan.monthly_price_kes, method='cash', reference=None,
                    status='recorded', paid_at=utcnow-timedelta(days=i % 11, hours=2)))
            # Build attendance: the first three members are regular, 6-9 inactive,
            # 10-12 declining and others moderate. Never insert future visits.
            if i in range(6,10):
                offsets = [23, 30, 37]
            elif i in range(10,13):
                offsets = [3, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36]
            elif i in (18,19,22,23,24):
                offsets = []
            else:
                offsets = list(range(i % 3, 43, 3 if i < 3 else 5))
            for off in offsets:
                checked = datetime.combine(today-timedelta(days=off), time(9+(i%8), 0), tzinfo=ZoneInfo('Africa/Nairobi')).astimezone(timezone.utc)
                db.add(CheckIn(id=uuid4(), member_id=member.id, checked_in_at=checked,
                    source='manual', was_overridden=False, restriction_codes=[]))
            if i in range(15):
                p = programs[i%3]
                a = WorkoutAssignment(id=uuid4(), program_id=p.id, member_id=member.id,
                    starts_on=today-timedelta(days=15), status='in_progress' if i%2 else 'assigned',
                    notes='Demo coaching assignment — review technique with a trainer.')
                db.add(a)
            if i in range(18):
                db.add(MemberFitnessProfile(id=uuid4(), member_id=member.id,
                    primary_goal=['build_strength','improve_fitness','lose_weight'][i%3],
                    experience=['beginner','intermediate'][i%2], available_days_per_week=3,
                    session_duration_minutes=45, equipment_preferences=['full_gym'],
                    limitations=None, notes='Fictional demo fitness profile.',
                    review_status='awaiting_review' if i in (16,17) else 'trainer_approved',
                    recommended_program_id=programs[i%3].id,
                    final_program_id=programs[i%3].id if i<15 else None))
        db.flush()
        for j, (title, days_offset, capacity, registered) in enumerate([
            ('Saturday Strength Club', 2, 12, 9), ('HIIT Express', 4, 10, 9),
            ('Beginner Orientation', 6, 8, 8), ('Community Bootcamp', -6, 20, 12),
        ]):
            start_local = datetime.combine(today+timedelta(days=days_offset), time(10+j,0),tzinfo=ZoneInfo('Africa/Nairobi'))
            event = GymEvent(id=uuid4(),name=title,description='Fictional DemoFit class',
                starts_at=start_local.astimezone(timezone.utc),
                ends_at=(start_local+timedelta(hours=1)).astimezone(timezone.utc),
                capacity=capacity,confirmed_count=registered,status='published')
            db.add(event)
            db.flush()
            for member in people[:registered]:
                db.add(EventRegistration(id=uuid4(),event_id=event.id,member_id=member.id,status='confirmed'))
        db.commit()
    print('Seeded DemoFit Studio: 25 fictional members, subscriptions, payments, attendance, workouts and events.')

if __name__ == '__main__':
    main()
