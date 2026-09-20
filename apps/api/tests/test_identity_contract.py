"""Identity M4a public-contract and compatibility tests."""

from datetime import datetime, timezone

from cloudsite.identity import (
    FolderIdentityObservation as LegacyFolderIdentityObservation,
    IdentityObservation as LegacyIdentityObservation,
)
from cloudsite.identity.fingerprint import (
    folder_identity_fingerprint as legacy_folder_identity_fingerprint,
    identity_fingerprint as legacy_identity_fingerprint,
)
from cloudsite.modules.identity.contracts.public import (
    FolderIdentityObservation,
    IdentityObservation,
    folder_identity_fingerprint,
    identity_fingerprint,
)


def test_legacy_identity_types_are_exact_public_contract_types():
    assert LegacyIdentityObservation is IdentityObservation
    assert LegacyFolderIdentityObservation is FolderIdentityObservation


def test_legacy_fingerprint_functions_are_exact_module_domain_functions():
    assert legacy_identity_fingerprint is identity_fingerprint
    assert legacy_folder_identity_fingerprint is folder_identity_fingerprint


def test_resource_fingerprint_contract_preserves_v1_behavior():
    value = identity_fingerprint(
        size=42,
        modified_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        extension=".ZIP",
        mime_type="APPLICATION/ZIP",
    )
    same = identity_fingerprint(
        size=42,
        modified_at=datetime(2026, 9, 1),
        extension="zip",
        mime_type="application/zip",
    )
    assert value == same
    assert len(value) == 64


def test_folder_fingerprint_contract_is_order_independent():
    first = [
        {"name": "a", "is_dir": True},
        {"name": "b.txt", "is_dir": False},
    ]
    second = list(reversed(first))
    assert folder_identity_fingerprint(first) == folder_identity_fingerprint(second)
