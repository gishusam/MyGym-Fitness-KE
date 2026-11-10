"""Acceptance smoke tests for owner-only retention signals."""
from backend.app.core.auth import get_current_staff
from backend.app.main import app
from backend.app.models.staff_user import StaffRole


def test_owner_can_read_retention(client):
    response = client.get('/api/dashboard/retention')
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {'atRiskCount', 'inactiveCount', 'expiringCount', 'signals'}
    assert result['signals'] == []


def test_receptionist_cannot_read_owner_retention(client, staff_factory):
    staff = staff_factory(StaffRole.RECEPTIONIST)
    app.dependency_overrides[get_current_staff] = lambda: staff
    assert client.get('/api/dashboard/retention').status_code == 403


def test_trainer_cannot_read_owner_retention(client, staff_factory):
    staff = staff_factory(StaffRole.TRAINER)
    app.dependency_overrides[get_current_staff] = lambda: staff
    assert client.get('/api/dashboard/retention').status_code == 403
