"""Notifications ORM ownership compatibility tests."""

from cloudsite.models import Notification as LegacyNotification
from cloudsite.modules.notifications.infrastructure.models import Notification
from cloudsite.platform.db import StateBase


def test_legacy_notification_export_is_exact_module_class():
    assert LegacyNotification is Notification


def test_notification_orm_is_owned_by_notifications_infrastructure():
    assert Notification.__module__ == (
        "cloudsite.modules.notifications.infrastructure.models"
    )


def test_notification_table_remains_registered_on_state_metadata():
    assert "notifications" in StateBase.metadata.tables
    assert Notification.__tablename__ == "notifications"
