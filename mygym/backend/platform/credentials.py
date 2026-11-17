"""Encryption helpers for tenant database connection URLs stored in the registry."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.engine import make_url


class CredentialConfigurationError(ValueError):
    """Raised when tenant connection credentials cannot be safely handled."""


def _fernet() -> MultiFernet:
    configured = os.getenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", "")
    keys = [value.strip() for value in configured.split(",") if value.strip()]
    if not keys:
        raise CredentialConfigurationError(
            "PLATFORM_CREDENTIAL_ENCRYPTION_KEYS must be configured"
        )
    try:
        return MultiFernet([Fernet(key.encode("ascii")) for key in keys])
    except (UnicodeEncodeError, ValueError):
        raise CredentialConfigurationError(
            "PLATFORM_CREDENTIAL_ENCRYPTION_KEYS is invalid"
        ) from None


def _validate_database_url(database_url: str) -> None:
    try:
        parsed = make_url(database_url)
    except (TypeError, ValueError):
        raise CredentialConfigurationError("Invalid tenant database URL") from None
    if (
        parsed.get_backend_name() != "postgresql"
        or not parsed.host
        or not parsed.database
        or not parsed.username
        or parsed.password is None
    ):
        raise CredentialConfigurationError(
            "Tenant database URL must be a credentialed PostgreSQL URL"
        )


def encrypt_database_url(database_url: str) -> str:
    """Validate and encrypt a PostgreSQL connection URL; never return plaintext."""
    _validate_database_url(database_url)
    return _fernet().encrypt(database_url.encode("utf-8")).decode("ascii")


def decrypt_database_url(ciphertext: str) -> str:
    """Decrypt and revalidate a stored URL, failing closed on key/config errors."""
    try:
        database_url = _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError):
        raise CredentialConfigurationError(
            "Stored tenant database credential could not be decrypted"
        ) from None
    _validate_database_url(database_url)
    return database_url


def rotate_database_url_ciphertext(ciphertext: str) -> str:
    """Re-encrypt ciphertext with the first configured key in the key list."""
    try:
        return _fernet().rotate(ciphertext.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeEncodeError):
        raise CredentialConfigurationError(
            "Stored tenant database credential could not be rotated"
        ) from None
