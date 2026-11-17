"""Rotate encrypted tenant database URLs after updating the server-side key list."""
from __future__ import annotations

import argparse

from sqlalchemy import select

from backend.platform.app import GymTenant, PlatformAudit, platform_session_factory
from backend.platform.credentials import rotate_database_url_ciphertext


def rotate_credentials(*, apply: bool = False) -> int:
    """Validate all stored tenant credentials, or re-encrypt them with the first key."""
    rotated = 0
    with platform_session_factory()() as session:
        with session.begin():
            gyms = session.scalars(
                select(GymTenant)
                .where(GymTenant.database_url_ciphertext.is_not(None))
                .order_by(GymTenant.id)
                .with_for_update()
            ).all()
            for gym in gyms:
                rotated_url = rotate_database_url_ciphertext(gym.database_url_ciphertext)
                rotated += 1
                if apply:
                    gym.database_url_ciphertext = rotated_url
                    session.add(
                        PlatformAudit(
                            actor_clerk_user_id="system:credential-rotator",
                            gym_id=gym.id,
                            event="tenant_database_credential_rotated",
                        )
                    )
    return rotated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-encrypt platform tenant URLs with the first configured Fernet key"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write rotated ciphertexts; otherwise validate without changing the registry",
    )
    args = parser.parse_args()
    try:
        count = rotate_credentials(apply=args.apply)
    except Exception as exc:
        parser.exit(
            1,
            f"Credential rotation failed ({type(exc).__name__}); check protected operator logs.\n",
        )
    print(
        f"{'Rotated' if args.apply else 'Validated'} {count} tenant credential record(s)."
    )
    if not args.apply:
        print("DRY RUN; pass --apply to re-encrypt the records.")


if __name__ == "__main__":
    main()
