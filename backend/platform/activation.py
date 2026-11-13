"""Read-only verification of an explicitly linked local gym database.

Development-only resolver: no database URL comes from client input or platform rows.
Use a provisioned per-tenant credential/connection resolver in production.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


KNOWN_LOCAL_DATABASES = {"mygym_fitness_dev", "mygym_demo"}


class GymActivationError(Exception):
    pass


@dataclass(frozen=True)
class GymVerification:
    database_name: str
    gym_name: str
    owner_clerk_user_id: str


def verify_linked_gym(database_ref: str, *, source_url: str | None = None, platform_url: str | None = None) -> GymVerification:
    if database_ref not in KNOWN_LOCAL_DATABASES:
        raise GymActivationError("This database is not configured for local activation")
    source_url = source_url if source_url is not None else os.environ.get("GYM_SOURCE_DATABASE_URL", "")
    platform_url = platform_url if platform_url is not None else os.environ.get("PLATFORM_DATABASE_URL", "")
    if not source_url or not platform_url:
        raise GymActivationError("Configure GYM_SOURCE_DATABASE_URL and PLATFORM_DATABASE_URL on the platform API")
    try:
        source = make_url(source_url)
        platform = make_url(platform_url)
        if source.get_backend_name() != 'postgresql' or platform.get_backend_name() != 'postgresql':
            raise GymActivationError('PostgreSQL connection required')
        if source.database != 'mygym_fitness_dev' or platform.database != 'mygym_platform':
            raise GymActivationError('Source and platform database names do not match the expected local environment')
        if (source.host, source.port) != (platform.host, platform.port):
            raise GymActivationError('Gym and platform connection servers do not match')
        if database_ref == platform.database:
            raise GymActivationError('The platform database cannot be activated as a gym')
        url = source.set(database=database_ref)
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as db:
                if db.execute(text('SELECT current_database()')).scalar_one() != database_ref:
                    raise GymActivationError('Connected database differs from the registered gym database')
                if not {'gym_settings', 'staff_users', 'members'}.issubset(set(inspect(db).get_table_names())):
                    raise GymActivationError('Required gym tables are missing')
                settings = db.execute(text('SELECT gym_name, owner_bootstrap_completed FROM gym_settings WHERE id = 1')).one_or_none()
                if settings is None or not settings[0] or not settings[1]:
                    raise GymActivationError('Gym settings or owner bootstrap are incomplete')
                owners = db.execute(text("SELECT clerk_user_id FROM staff_users WHERE role = 'owner' AND status = 'active'")).all()
                if len(owners) != 1 or not isinstance(owners[0][0], str) or not owners[0][0].startswith('user_'):
                    raise GymActivationError('Exactly one active Owner with a Clerk user ID is required')
                return GymVerification(database_ref, settings[0], owners[0][0])
        finally:
            engine.dispose()
    except GymActivationError:
        raise
    except Exception as exc:
        # Avoid leaking secrets, DB usernames, and host addresses to API callers.
        raise GymActivationError('Unable to verify the linked gym database') from exc
