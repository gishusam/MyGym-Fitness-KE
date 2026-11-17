"""Operator-only per-gym database provisioning. Never invoked from an HTTP request."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from backend.platform.app import GymTenant, PlatformAudit, platform_session_factory
from backend.platform.credentials import (
    CredentialConfigurationError,
    decrypt_database_url,
    encrypt_database_url,
)

DB_NAME_PATTERN = re.compile(r"^mygym_tenant_[a-z0-9_]{3,48}$")


def db_name_for_slug(slug: str) -> str:
    """Derive a constrained, deterministic Postgres identifier from a gym slug."""
    result = "mygym_tenant_" + slug.replace("-", "_")
    if not DB_NAME_PATTERN.fullmatch(result) or len(result) > 63:
        raise ValueError("Gym slug cannot be mapped to an allowed database name")
    return result


def database_role_for_slug(slug: str) -> str:
    """Derive a short, stable, tenant-specific PostgreSQL login role."""
    if not re.fullmatch(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug):
        raise ValueError("Gym slug cannot be mapped to a database role")
    return "mygym_" + hashlib.sha256(slug.encode("utf-8")).hexdigest()[:24]


def _prepare_tenant_url(
    gym: GymTenant,
    *,
    db_name: str,
    admin_url: str,
    platform_url: str,
) -> tuple[str, str, str, str]:
    """Return maintenance URL, per-tenant URL, role, and encrypted URL."""
    admin = make_url(admin_url)
    platform = make_url(platform_url)
    if admin.get_backend_name() != "postgresql" or platform.get_backend_name() != "postgresql":
        raise ValueError("Provisioning requires PostgreSQL maintenance and platform URLs")
    if admin.database in {db_name, platform.database} or platform.database == db_name:
        raise ValueError("Provisioning connections must not target a tenant or platform database")

    role = database_role_for_slug(gym.slug)
    if gym.database_url_ciphertext:
        try:
            tenant_url = decrypt_database_url(gym.database_url_ciphertext)
        except CredentialConfigurationError as exc:
            raise ValueError(str(exc)) from None
        tenant = make_url(tenant_url)
        if (
            tenant.database != db_name
            or tenant.username != role
            or (tenant.host, tenant.port) != (admin.host, admin.port)
        ):
            raise ValueError("Stored tenant connection does not match its registered gym")
        return admin_url, tenant_url, role, gym.database_url_ciphertext

    tenant_url = admin.set(
        database=db_name,
        username=role,
        password=secrets.token_urlsafe(32),
    ).render_as_string(hide_password=False)
    try:
        encrypted_url = encrypt_database_url(tenant_url)
    except CredentialConfigurationError as exc:
        raise ValueError(str(exc)) from None
    return admin_url, tenant_url, role, encrypted_url


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
            try:
                admin_url, migrated_url, role, encrypted_url = _prepare_tenant_url(
                    gym,
                    db_name=db_name,
                    admin_url=os.environ["GYM_PROVISION_ADMIN_URL"],
                    platform_url=os.environ["PLATFORM_DATABASE_URL"],
                )
            except KeyError as exc:
                raise ValueError(f"{exc.args[0]} must be configured") from None
            gym.database_url_ciphertext = encrypted_url
            gym.status = "provisioning"
            session.add(PlatformAudit(actor_clerk_user_id="system:provisioner", gym_id=gym.id, event="provisioning_started"))

    try:
        # Psycopg's SQL identifier quoting prevents SQL through database or role names.
        import psycopg
        from psycopg import sql

        with psycopg.connect(admin_url, autocommit=True) as conn:
            role_info = conn.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolinherit, rolreplication, rolbypassrls "
                "FROM pg_roles WHERE rolname = %s",
                (role,),
            ).fetchone()
            if role_info is None:
                tenant_password = make_url(migrated_url).password
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role), sql.Literal(tenant_password))
                )
            elif not role_info[0] or any(role_info[1:]):
                raise ValueError("Existing tenant role has unexpected privileges; refusing to reuse it")

            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)).fetchone()
            if exists is None:
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(db_name), sql.Identifier(role)))
            else:
                # Retry only against a database owned by this gym's dedicated role.
                owner = conn.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (db_name,)).fetchone()[0]
                if owner != role:
                    raise ValueError("Existing database has an unexpected owner; refusing to modify it")

        env = os.environ.copy()
        # Migration subprocesses need only the per-gym URL, never operator/platform credentials.
        for key in (
            "PLATFORM_DATABASE_URL",
            "PLATFORM_CREDENTIAL_ENCRYPTION_KEYS",
            "PLATFORM_ADMIN_CLERK_IDS",
            "GYM_SOURCE_DATABASE_URL",
            "GYM_PROVISION_ADMIN_URL",
            "GYM_PROVISION_TENANT_URL",
            "GYM_PROVISION_OWNER_ROLE",
        ):
            env.pop(key, None)
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
            gym.database_ref = db_name
            gym.status = "awaiting_owner"
            session.add(PlatformAudit(actor_clerk_user_id="system:provisioner", gym_id=gym.id, event="database_provisioned"))
    return db_name


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a registered MyGym gym database")
    parser.add_argument("--gym-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Create DB and run Alembic; otherwise dry run")
    args = parser.parse_args()
    try:
        name = provision(args.gym_id, apply=args.apply)
    except Exception as exc:
        # Do not print connection URLs, passwords, or provider diagnostics to the terminal.
        parser.exit(1, f"Provisioning failed ({type(exc).__name__}); check the protected operator logs.\n")
    print(f"{'Provisioned' if args.apply else 'Would provision'} database: {name}")
    if args.apply:
        print("Status: awaiting_owner. Bootstrap a real verified Clerk owner before activation.")


if __name__ == "__main__":
    main()
