"""Operator-only: provision a pending customer gym and bind its verified Clerk owner.

Run from trusted terminal with explicit DB provisioning credentials. No HTTP endpoint can run this.
"""
from __future__ import annotations

import argparse
import os
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from backend.platform.app import GymTenant, PlatformAudit, platform_session_factory
from backend.platform.provisioning import provision, db_name_for_slug
from backend.app.models.gym_settings import GymSettings
from backend.app.models.staff_user import StaffUser, StaffRole, StaffStatus
from backend.app.models.audit_log import AuditLog
from backend.app.services.clerk import get_verified_clerk_profile


def fulfill(gym_id: str, apply: bool = False) -> str:
    with platform_session_factory()() as db:
        gym = db.get(GymTenant, gym_id)
        if gym is None or gym.environment_kind != "customer" or not gym.owner_clerk_user_id:
            raise ValueError("Not a registered customer gym with a verified owner")
        if gym.status not in {"pending_provisioning", "provision_failed", "awaiting_owner"}:
            raise ValueError(f"Gym is not eligible for signup fulfillment: {gym.status}")
        owner_id = gym.owner_clerk_user_id
        gym_name = gym.name
        db_name = db_name_for_slug(gym.slug)
    if not apply:
        return f"Would initialize {gym_name} ({gym_id}), database {db_name}"
    secret = os.environ.get("CLERK_SECRET_KEY")
    if not secret:
        raise ValueError("CLERK_SECRET_KEY is required for owner verification")
    owner_name, verified_emails = get_verified_clerk_profile(owner_id, secret)
    if not verified_emails:
        raise ValueError("Owner must have a verified Clerk email")
    owner_email = sorted(verified_emails)[0]
    if gym.status in {"pending_provisioning", "provision_failed"}:
        provision(gym_id, apply=True)
    tenant_root = make_url(os.environ["GYM_PROVISION_TENANT_URL"])
    tenant_url = tenant_root.set(database=db_name).render_as_string(hide_password=False)
    platform_db_name = make_url(os.environ["PLATFORM_DATABASE_URL"]).database
    if db_name == platform_db_name or db_name == make_url(os.environ.get("DATABASE_URL", tenant_url)).database and db_name in {"mygym_fitness_dev", "mygym_demo"}:
        raise ValueError("Unsafe tenant database target")
    engine = create_engine(tenant_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            with session.begin():
                settings = session.scalar(select(GymSettings).where(GymSettings.id == 1).with_for_update())
                if settings is None:
                    settings = GymSettings(id=1, gym_name=gym_name, timezone="Africa/Nairobi")
                    session.add(settings)
                    session.flush()
                current = list(session.scalars(select(StaffUser).with_for_update()).all())
                if current and (len(current) != 1 or current[0].clerk_user_id != owner_id or current[0].role != StaffRole.OWNER.value):
                    raise ValueError("Tenant contains unexpected staff; refusing to take ownership")
                if current:
                    owner = current[0]
                else:
                    owner = StaffUser(clerk_user_id=owner_id, name=owner_name or "Gym owner", email=owner_email,
                                      role=StaffRole.OWNER.value, status=StaffStatus.ACTIVE.value)
                    session.add(owner)
                    session.flush()
                    session.add(AuditLog(actor_staff_id=owner.id, action="staff.owner_bootstrapped",
                                         entity_type="staff_user", entity_id=str(owner.id), details={"source":"verified_signup"}))
                settings.gym_name = gym_name
                settings.owner_bootstrap_completed = True
                settings.updated_by = owner.id
    finally:
        engine.dispose()
    with platform_session_factory()() as db:
        with db.begin():
            gym = db.scalar(select(GymTenant).where(GymTenant.id == gym_id).with_for_update())
            if gym is None or gym.owner_clerk_user_id != owner_id or gym.status != "awaiting_owner":
                raise ValueError("Registry changed while provisioning; verify manually before activation")
            gym.database_ref = db_name
            gym.status = "active"
            db.add(PlatformAudit(actor_clerk_user_id="system:signup-fulfillment", gym_id=gym_id, event="customer_gym_activated"))
    return f"Activated {gym_name}; database {db_name}; verified owner {owner_id}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gym-id", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    try:
        print(fulfill(args.gym_id, apply=args.apply))
    except Exception as exc:
        ap.exit(1, f"Signup fulfillment failed: {type(exc).__name__}: {exc}\n")

if __name__ == "__main__":
    main()
