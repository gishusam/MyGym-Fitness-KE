from __future__ import annotations

import base64
import binascii
import re
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str | None = None
    clerk_publishable_key: str | None = None
    clerk_secret_key: str | None = None
    initial_owner_email: str | None = None

    def clerk_frontend_api_host(self) -> str:
        key = self.clerk_publishable_key
        if not key:
            raise RuntimeError("CLERK_PUBLISHABLE_KEY is not configured")

        parts = key.split("_", 2)
        if len(parts) != 3 or parts[0] != "pk" or parts[1] not in {"test", "live"}:
            raise RuntimeError("CLERK_PUBLISHABLE_KEY has an invalid format")

        encoded_host = parts[2].removesuffix("$")
        try:
            host = base64.urlsafe_b64decode(
                encoded_host + "=" * (-len(encoded_host) % 4)
            ).decode("ascii")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise RuntimeError("CLERK_PUBLISHABLE_KEY has an invalid host") from error

        host = host.removesuffix("$").lower()
        if not host or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise RuntimeError("CLERK_PUBLISHABLE_KEY has an invalid host")
        return host

    def clerk_issuer(self) -> str:
        return f"https://{self.clerk_frontend_api_host()}"

    def clerk_jwks_url(self) -> str:
        return f"{self.clerk_issuer()}/.well-known/jwks.json"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
