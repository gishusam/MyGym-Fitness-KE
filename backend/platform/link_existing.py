"""Operator-only, idempotent registration of the two known LOCAL MyGym databases.

No credentials/DB URLs are exposed through platform API or stored in registry.
No members, payments, staff, or workout records are modified. No DBs are created.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.platform.app import GymTenant, PlatformAudit, platform_session_factory


@dataclass(frozen=True)
class ExistingGym:
    slug: str
    name: str
    database: str
    environment_kind: str


KNOWN_GYMS = (
    ExistingGym("mygym-fitness-ke", "MyGym Fitness KE", "mygym_fitness_dev", "development"),
    ExistingGym("demofit-studio", "DemoFit Studio", "mygym_demo", "demo"),
)


def verify_existing_database(base_url: str, expected_name: str, platform_url: str) -> str:
    source = make_url(base_url)
    platform = make_url(platform_url)
    if source.get_backend_name() != "postgresql" or platform.get_backend_name() != "postgresql":
        raise ValueError("Only PostgreSQL databases are supported")
    if source.database != "mygym_fitness_dev":
        raise ValueError("GYM_SOURCE_DATABASE_URL must target mygym_fitness_dev")
    if platform.database == expected_name:
        raise ValueError("Cannot register platform database as a gym")
    gym_url = source.set(database=expected_name)
    engine = create_engine(gym_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            actual_db = conn.execute(text("SELECT current_database() ")).scalar_one()
            if actual_db != expected_name:
                raise ValueError("Connected database does not match expected gym")
            tables = set(inspect(conn).get_table_names())
            if not {"gym_settings", "staff_users", "members"}.issubset(tables):
                raise ValueError(f"{expected_name}: missing operational MyGym tables")
            actual_gym_name = conn.execute(text("SELECT gym_name FROM gym_settings WHERE id = 1")).scalar_one_or_none()
            if not actual_gym_name:
                raise ValueError(f"{expected_name}: missing gym settings")
            return str(actual_gym_name)
    finally:
        engine.dispose()


def sync_known_gyms(*, apply: bool = False, verify=verify_existing_database,
                    session_factory=platform_session_factory) -> list[str]:
    source = os.environ.get("GYM_SOURCE_DATABASE_URL", "")
    platform = os.environ.get("PLATFORM_DATABASE_URL", "")
    if not source or not platform:
        raise RuntimeError("Set both GYM_SOURCE_DATABASE_URL and PLATFORM_DATABASE_URL")
    if make_url(source).database == make_url(platform).database:
        raise ValueError("Platform database must be separate from gym databases")

    # Verify BOTH databases before making ANY registry mutations.
    results = [(gym, verify(source, gym.database, platform)) for gym in KNOWN_GYMS]
    output: list[str] = []
    with session_factory()() as db:
        with db.begin():
            # Acquire locks on existing rows. Duplicate ref cannot be silently stolen.
            existing = db.scalars(select(GymTenant).with_for_update()).all()
            by_slug = {row.slug: row for row in existing}
            by_ref = {row.database_ref: row for row in existing if row.database_ref}
            for gym, verified_name in results:
                match = by_slug.get(gym.slug)
                ref_owner = by_ref.get(gym.database)
                if ref_owner and ref_owner is not match:
                    raise ValueError(f"{gym.database} is already linked to another gym")
                if match and match.database_ref not in (None, gym.database):
                    raise ValueError(f"{gym.slug} is linked to a different database")
                if match and match.status in {"provisioning", "active", "suspended", "archived"} and match.database_ref is None:
                    raise ValueError(f"{gym.slug} has incompatible status {match.status}")
                action = "already linked" if match and match.database_ref == gym.database else ("link existing" if match else "register and link")
                output.append(f"{gym.name} [{gym.environment_kind}] — {action}; database {gym.database}; settings '{verified_name}'")
                if not apply or action == "already linked":
                    continue
                if match is None:
                    match = GymTenant(name=gym.name, slug=gym.slug, status="linked", environment_kind=gym.environment_kind)
                    db.add(match)
                    db.flush()
                match.environment_kind = gym.environment_kind
                match.database_ref = gym.database
                # A linked database is NOT necessarily an activated/accessible gym.
                if match.status in {"pending_provisioning", "provision_failed", "awaiting_owner"}:
                    match.status = "linked"
                db.add(PlatformAudit(actor_clerk_user_id="system:local-import", gym_id=match.id, event="existing_database_linked"))
            if not apply:
                db.rollback()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Register/link known local MyGym environments without modifying their databases")
    parser.add_argument("--apply", action="store_true", help="Write registry changes; otherwise dry-run")
    args = parser.parse_args()
    try:
        for line in sync_known_gyms(apply=args.apply):
            print(line)
        print("Registry updated." if args.apply else "DRY RUN; registry unchanged. Pass --apply to link.")
    except Exception as exc:
        parser.exit(1, f"Linking stopped: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
