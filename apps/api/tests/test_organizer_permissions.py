from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from cloudsite.config import settings
from cloudsite.services.organizer_permissions import active_organizer_user, require_organizer_actor


def _user(user_id=7, status="active", disabled_at=None, deleted_at=None):
    return SimpleNamespace(id=user_id, status=status, disabled_at=disabled_at, deleted_at=deleted_at)


def test_exactly_designated_user_is_allowed(monkeypatch):
    monkeypatch.setattr(settings, "organizer_user_id", 7)
    require_organizer_actor(_user())
    with pytest.raises(HTTPException) as error:
        require_organizer_actor(_user(user_id=8))
    assert error.value.status_code == 403


@pytest.mark.parametrize("configured,status,disabled,deleted", [
    (0, "active", None, None),
    (7, "disabled", None, None),
    (7, "active", object(), None),
    (7, "active", None, object()),
])
def test_inactive_or_unconfigured_is_denied(monkeypatch, configured, status, disabled, deleted):
    monkeypatch.setattr(settings, "organizer_user_id", configured)
    with pytest.raises(HTTPException):
        require_organizer_actor(_user(status=status, disabled_at=disabled, deleted_at=deleted))


async def test_scheduler_identity_requires_existing_active_user(monkeypatch):
    monkeypatch.setattr(settings, "organizer_user_id", 7)

    class Session:
        async def get(self, model, key):
            assert key == 7
            return _user(status="disabled")

    assert await active_organizer_user(Session()) is None
