"""Delivery ORM ownership compatibility tests."""

from cloudsite.models import (
    DownloadDiagnostic as LegacyDownloadDiagnostic,
    DownloadEvent as LegacyDownloadEvent,
)
from cloudsite.modules.delivery.infrastructure.models import (
    DownloadDiagnostic,
    DownloadEvent,
)
from cloudsite.platform.db import StateBase


def test_legacy_delivery_orm_exports_are_exact_module_classes():
    assert LegacyDownloadEvent is DownloadEvent
    assert LegacyDownloadDiagnostic is DownloadDiagnostic


def test_delivery_orm_classes_are_owned_by_delivery_infrastructure():
    assert DownloadEvent.__module__ == (
        "cloudsite.modules.delivery.infrastructure.models"
    )
    assert DownloadDiagnostic.__module__ == (
        "cloudsite.modules.delivery.infrastructure.models"
    )


def test_delivery_tables_remain_registered_on_state_metadata():
    assert "download_events" in StateBase.metadata.tables
    assert "download_diagnostics" in StateBase.metadata.tables


def test_delivery_table_names_are_unchanged():
    assert DownloadEvent.__tablename__ == "download_events"
    assert DownloadDiagnostic.__tablename__ == "download_diagnostics"
