from __future__ import annotations

import httpx
from fastapi import HTTPException


def get_verified_clerk_profile(
    user_id: str, secret_key: str
) -> tuple[str, set[str]]:
    try:
        response = httpx.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=8.0,
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Could not verify your account with the sign-in provider",
                "code": "clerk_profile_unavailable",
            },
        ) from None

    if response.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Could not verify your account with the sign-in provider",
                "code": "clerk_profile_unavailable",
            },
        )

    try:
        profile = response.json()
        verified_emails = {
            item["email_address"].strip().casefold()
            for item in profile.get("email_addresses", [])
            if item.get("email_address")
            and item.get("verification", {}).get("status") == "verified"
        }
    except (AttributeError, TypeError, ValueError):
        raise HTTPException(
            status_code=503,
            detail={
                "error": "The sign-in provider returned an invalid account profile",
                "code": "clerk_profile_unavailable",
            },
        ) from None

    first_name = (profile.get("first_name") or "").strip()
    last_name = (profile.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    if not full_name:
        full_name = profile.get("username") or ""

    return full_name.strip(), verified_emails
