from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas.gym_settings import GymSettingsUpdate


def test_gym_settings_update_accepts_partial_values() -> None:
    update = GymSettingsUpdate(attendanceDuplicateIntervalMinutes=8)
    assert update.model_dump(exclude_unset=True) == {
        "attendance_duplicate_interval_minutes": 8
    }


def test_gym_settings_update_rejects_empty_patch() -> None:
    with pytest.raises(ValidationError):
        GymSettingsUpdate.model_validate({})


def test_gym_settings_update_rejects_invalid_timezone() -> None:
    with pytest.raises(ValidationError):
        GymSettingsUpdate(timezone="Mars/Olympus")


def test_updated_at_fixture_is_timezone_aware() -> None:
    value = datetime.now(UTC)
    assert value.tzinfo is not None
