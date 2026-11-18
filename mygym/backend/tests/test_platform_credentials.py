from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.platform.app import GymTenant, PlatformAudit, PlatformBase
from backend.platform.credentials import (
    CredentialConfigurationError,
    decrypt_database_url,
    encrypt_database_url,
    rotate_database_url_ciphertext,
)
from backend.platform.rotate_credentials import rotate_credentials


def _key(seed: bytes) -> str:
    return base64.urlsafe_b64encode(seed).decode("ascii")


def test_database_urls_are_encrypted_and_round_trip(monkeypatch):
    monkeypatch.setenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", _key(b"a" * 32))
    url = "postgresql+psycopg://tenant-user:private-password@db.example:5432/gym_db"

    ciphertext = encrypt_database_url(url)

    assert ciphertext != url
    assert "private-password" not in ciphertext
    assert decrypt_database_url(ciphertext) == url


def test_credentials_fail_closed_without_a_key(monkeypatch):
    monkeypatch.delenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", raising=False)

    with pytest.raises(CredentialConfigurationError, match="must be configured"):
        encrypt_database_url(
            "postgresql+psycopg://tenant-user:private-password@db.example:5432/gym_db"
        )


def test_credentials_fail_closed_on_tampering(monkeypatch):
    monkeypatch.setenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", _key(b"a" * 32))
    ciphertext = encrypt_database_url(
        "postgresql+psycopg://tenant-user:private-password@db.example:5432/gym_db"
    )
    tampered = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]

    with pytest.raises(CredentialConfigurationError, match="could not be decrypted"):
        decrypt_database_url(tampered)


def test_rotation_reencrypts_with_the_first_key(monkeypatch):
    old_key = _key(b"a" * 32)
    new_key = _key(b"b" * 32)
    url = "postgresql+psycopg://tenant-user:private-password@db.example:5432/gym_db"
    monkeypatch.setenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", old_key)
    ciphertext = encrypt_database_url(url)

    monkeypatch.setenv(
        "PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", f"{new_key},{old_key}"
    )
    rotated = rotate_database_url_ciphertext(ciphertext)

    assert Fernet(new_key.encode()).decrypt(rotated.encode()).decode() == url
    assert decrypt_database_url(rotated) == url


def test_rotation_command_is_dry_run_unless_apply(monkeypatch, tmp_path):
    old_key = _key(b"a" * 32)
    new_key = _key(b"b" * 32)
    url = "postgresql+psycopg://tenant-user:private-password@db.example:5432/gym_db"
    monkeypatch.setenv("PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", old_key)
    ciphertext = encrypt_database_url(url)
    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}")
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            GymTenant(
                id="gym-one",
                slug="gym-one",
                name="Gym One",
                database_url_ciphertext=ciphertext,
            )
        )
        session.commit()
    monkeypatch.setattr(
        "backend.platform.rotate_credentials.platform_session_factory",
        lambda: factory,
    )
    monkeypatch.setenv(
        "PLATFORM_CREDENTIAL_ENCRYPTION_KEYS", f"{new_key},{old_key}"
    )

    assert rotate_credentials() == 1
    with factory() as session:
        assert session.get(GymTenant, "gym-one").database_url_ciphertext == ciphertext
        assert session.scalars(select(PlatformAudit)).all() == []

    assert rotate_credentials(apply=True) == 1
    with factory() as session:
        rotated = session.get(GymTenant, "gym-one").database_url_ciphertext
        assert Fernet(new_key.encode()).decrypt(rotated.encode()).decode() == url
        assert session.scalar(
            select(PlatformAudit).where(
                PlatformAudit.event == "tenant_database_credential_rotated"
            )
        ) is not None
    engine.dispose()
