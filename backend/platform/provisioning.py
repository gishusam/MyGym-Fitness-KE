"""Operator-only per-gym database provisioning. Never invoked from an HTTP request."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from backend.platform.app import GymTenant, PlatformAudit, platform_session_factory

DB_NAME_PATTERN = re.compile(r"^mygym_tenant_[a-z0-9_]{3,48}$")
ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def db_name_for_slug(slug: str) -> str:
    """Derive a constrained, deterministic Postgres identifier from a gym slug."""
    result = "mygym_tenant_" + slug.replace("-", "_")
    if not DB_NAME_PATTERN.fullmatch(result) or len(result) > 63:
        raise ValueError("Gym slug cannot be mapped to an allowed database name")
    return result


def provision(gym_id: str, *, apply: bool = False) -> str:
    """Provision an explicitly registered gym, or return its proposed database name."""
    # Open a dedicated platform connection and lock the row, avoiding two workers
    # provisioning the same gym simultaneously.
    with platform_session_factory()() as session:
        with session.begin():
            gym = session.scalar(select(GymTenant).where(GymTenant.id == gym_id).with_for_update())
            if gym is None:
                raise ValueError("Unknown gym ID")
            db_name = db_name_for_slug(gym.slug)
            if gym.status not in {"pending_provisioning", "provision_failed"}:
                raise ValueError(f"Gym is not eligible for provisioning (status={gym.status})")
            if not apply:
                return db_name
            gym.status = "provisioning"
            session.add(PlatformAudit(actor_clerk_user_id="system:provisioner", gym_id=gym.id, event="provisioning_started"))

    try:
        admin_url = os.environ["GYM_PROVISION_ADMIN_URL"]
        tenant_url = os.environ["GYM_PROVISION_TENANT_URL"]
        owner_role = os.environ["GYM_PROVISION_OWNER_ROLE"]
        if not ROLE_PATTERN.fullmatch(owner_role):
            raise ValueError("Invalid database owner role identifier")
        admin_parsed = make_url(admin_url)
        tenant_parsed = make_url(tenant_url)
        if admin_parsed.database == tenant_parsed.database == db_name:
            raise ValueError("Provisioning connections must target maintenance databases")
        # This guard checks that operator configuration isn't pointing at the platform DB.
        if make_url(os.environ["PLATFORM_DATABASE_URL"]).database in {db_name, admin_parsed.database, tenant_parsed.database}:
            raise ValueError("Provisioning connections must not target the platform database")

        # Psycopg's SQL identifier quoting prevents arbitrary SQL through gym slugs / roles.
        import psycopg
        from psycopg import sql

        with psycopg.connect(admin_url, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)).fetchone()
            if exists is None:
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(db_name), sql.Identifier(owner_role)))
            else:
                # Retry only against the pre-existing database owned by our tenant role.
                owner = conn.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (db_name,)).fetchone()[0]
                if owner != owner_role:
                    raise ValueError("Existing database has an unexpected owner; refusing to modify it")

        migrated_url = tenant_parsed.set(database=db_name).render_as_string(hide_password=False)
        env = os.environ.copy()
        env["DATABASE_URL"] = migrated_url
        project_root = Path(__file__).resolve().parents[2]
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
            cwd=project_root, env=env, check=True,
        )
        # Verify the schema from the tenant's own login, not from the superuser.
        engine = create_engine(migrated_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('staff_users','gym_settings','members')")).scalar_one()
                if count != 3:
                    raise RuntimeError("Tenant migrations did not create expected operational tables")
        finally:
            engine.dispose()
    except Exception:
        with platform_session_factory()() as session:
            with session.begin():
                gym = session.get(GymTenant, gym_id)
                if gym and gym.status == "provisioning":
                    gym.status = "provision_failed"
                    session.add(PlatformAudit(actor_clerk_user_id="system:provisioner", gym_id=gym_id, event="provisioning_failed"))
        raise

    with platform_session_factory()() as session:
        with session.begin():
            gym = session.get(GymTenant, gym_id)
            if gym is None or gym.status != "provisioning":
                raise RuntimeError("Unexpected gym provisioning state")
            # A database is not a usable gym until its owner has been bootstrapped.
            gym.status = "awaiting_owner"
            session.add(PlatformAudit(actor_clerk_user_id="system:provisioner", gym_id=gym_id, event="database_provisioned"))
    return db_name


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a registered MyGym gym database")
    parser.add_argument("--gym-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Create DB and run Alembic; otherwise dry run")
    args = parser.parse_args()
    try:
        name = provision(args.gym_id, apply=args.apply)
    except Exception as exc:
        parser.exit(1, f"Provisioning failed: {type(exc).__name__}: {exc}\n")
    print(f"{'Provisioned' if args.apply else 'Would provision'} database: {name}")
    if args.apply:
        print("Status: awaiting_owner. Bootstrap a real verified Clerk owner before activation.")


if __name__ == "__main__":
    main()
