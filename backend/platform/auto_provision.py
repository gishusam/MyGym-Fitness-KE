"""Automatic tenant provisioning for the local pilot.

Each request may schedule this function, but PostgreSQL advisory locks ensure
only one process acts on a gym. A failed or interrupted job is retried on the
next authenticated /signup/me request. No secrets/SQL are ever sent to clients.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, text
from backend.platform.app import GymTenant, PlatformAudit, platform_session_factory
from backend.platform.fulfill_signup import fulfill
from backend.platform.self_signup import auto_setup_available

logger = logging.getLogger(__name__)


def run_auto_provision(gym_id: str) -> None:
    if not auto_setup_available():
        return
    factory = platform_session_factory()
    # Session-level advisory lock survives separate fulfillment transactions.
    # Constant namespace key and UUID-derived key are stable across workers.
    import uuid
    try:
        lock_key = uuid.UUID(gym_id).int % (2**31 - 1)
    except ValueError:
        return
    with factory() as lock_session:
        # Explicitly acquire one pooled DB connection for the whole job.
        conn = lock_session.connection()
        got_lock = conn.execute(
            text("SELECT pg_try_advisory_lock(71042, :key)"), {"key": lock_key}
        ).scalar_one()
        if not got_lock:
            return
        try:
            with factory() as read_db:
                gym = read_db.get(GymTenant, gym_id)
                if gym is None or gym.environment_kind != "customer":
                    return
                if gym.status == "active":
                    return
                # Back off after a failed attempt; an authenticated poll can
                # retry later, but it must not trigger a 4-second failure loop.
                latest_failure = read_db.scalar(select(PlatformAudit.occurred_at)
                    .where(PlatformAudit.gym_id == gym_id,
                           PlatformAudit.event == "automatic_provisioning_failed")
                    .order_by(PlatformAudit.occurred_at.desc()).limit(1))
                if latest_failure is not None and latest_failure.replace(
                    tzinfo=latest_failure.tzinfo or timezone.utc
                ) > datetime.now(timezone.utc) - timedelta(seconds=45):
                    return
                if gym.status == "provisioning":
                    # A prior process may have been interrupted after setting
                    # the state to provisioning. Do not steal a live job: the
                    # advisory lock above rules out a concurrent active worker.
                    last = read_db.scalar(select(PlatformAudit.occurred_at)
                        .where(PlatformAudit.gym_id == gym_id,
                               PlatformAudit.event == "provisioning_started")
                        .order_by(PlatformAudit.occurred_at.desc()).limit(1))
                    if last is None or last.replace(tzinfo=last.tzinfo or timezone.utc) > datetime.now(timezone.utc) - timedelta(minutes=5):
                        return
                    with factory() as recover_db:
                        with recover_db.begin():
                            locked = recover_db.scalar(select(GymTenant).where(GymTenant.id == gym_id).with_for_update())
                            if locked is not None and locked.status == "provisioning":
                                locked.status = "provision_failed"
                                recover_db.add(PlatformAudit(actor_clerk_user_id="system:auto-provisioner",
                                    gym_id=gym_id, event="stale_provisioning_recovered"))
                elif gym.status not in {"pending_provisioning", "provision_failed", "awaiting_owner"}:
                    return
            try:
                result = fulfill(gym_id, apply=True)
                logger.info("Automatic gym activation succeeded: gym=%s message=%s", gym_id, result)
            except Exception:
                # Never log raw URLs, credentials or exceptions: DB libraries can
                # include DSNs in exception text. Audit only a generic failure.
                logger.error("Automatic gym activation failed: gym=%s; credentials and DB details intentionally suppressed", gym_id)
                with factory() as write_db:
                    with write_db.begin():
                        gym = write_db.scalar(select(GymTenant).where(GymTenant.id == gym_id).with_for_update())
                        if gym is not None and gym.status in {"pending_provisioning", "provisioning", "provision_failed"}:
                            gym.status = "provision_failed"
                            write_db.add(PlatformAudit(actor_clerk_user_id="system:auto-provisioner",
                                gym_id=gym_id, event="automatic_provisioning_failed"))
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(71042, :key)"), {"key": lock_key})
            lock_session.rollback()
