"""Identity resource repository/application port tests."""

from datetime import datetime, timezone

from cloudsite.modules.identity.application.ports import NullIdentityAuditSink
from cloudsite.modules.identity.application.resource_resolution import (
    resolve_resource_identities,
)
from cloudsite.modules.identity.domain.fingerprint import identity_fingerprint
from cloudsite.modules.identity.domain.models import IdentityObservation
from cloudsite.modules.identity.domain.records import (
    ResourceIdentityHistoryRecord,
    ResourceIdentityRecord,
)


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


class MemoryRepository:
    def __init__(self, records: list[ResourceIdentityRecord] | None = None) -> None:
        self.records = {record.resource_id: record for record in records or []}
        self.histories: list[ResourceIdentityHistoryRecord] = []
        self.commit_count = 0

    async def list_for_roots(
        self, root_mapping_ids: set[int | None]
    ) -> list[ResourceIdentityRecord]:
        if not root_mapping_ids or None in root_mapping_ids:
            return list(self.records.values())
        return [
            record
            for record in self.records.values()
            if record.root_mapping_id in root_mapping_ids
        ]

    async def id_exists(self, resource_id: str) -> bool:
        return resource_id in self.records

    async def add(self, record: ResourceIdentityRecord) -> None:
        self.records[record.resource_id] = record

    async def save(self, record: ResourceIdentityRecord) -> None:
        assert record.resource_id in self.records
        self.records[record.resource_id] = record

    async def add_history(self, record: ResourceIdentityHistoryRecord) -> None:
        self.histories.append(record)

    async def commit(self) -> None:
        self.commit_count += 1


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    async def record(self, *, level, action, message, created_at) -> None:
        self.events.append((level, action, message))


def observation(path: str) -> IdentityObservation:
    return IdentityObservation(
        path=path,
        name=path.rsplit("/", 1)[-1],
        root_mapping_id=1,
        size=42,
        modified_at=NOW,
        extension="zip",
        mime_type="application/zip",
    )


def existing(resource_id: str, path: str) -> ResourceIdentityRecord:
    return ResourceIdentityRecord(
        resource_id=resource_id,
        current_path=path,
        root_mapping_id=1,
        status="active",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_name=path.rsplit("/", 1)[-1],
        last_extension="zip",
        last_mime_type="application/zip",
        last_size=42,
        last_modified_at=NOW,
        identity_fingerprint=identity_fingerprint(
            size=42,
            modified_at=NOW,
            extension="zip",
            mime_type="application/zip",
        ),
        created_from="legacy_migration",
        updated_at=NOW,
    )


async def test_application_resolver_renames_through_repository_and_commits_once():
    repository = MemoryRepository([existing("r_old", "/root/A.zip")])
    audit = RecordingAuditSink()

    result = await resolve_resource_identities(
        repository,
        audit,
        [observation("/root/B.zip")],
        visible_paths={"/root/B.zip"},
        now=NOW,
    )

    assert result[0].resource_id == "r_old"
    assert result[0].match_type == "rename"
    assert repository.records["r_old"].current_path == "/root/B.zip"
    assert len(repository.histories) == 1
    assert repository.histories[0].event_type == "rename"
    assert repository.commit_count == 1
    assert audit.events[0][0:2] == ("INFO", "identity_rename_detected")


async def test_application_resolver_copy_allocates_new_identity_without_reusing_visible():
    repository = MemoryRepository([existing("r_old", "/root/A.zip")])

    result = await resolve_resource_identities(
        repository,
        NullIdentityAuditSink(),
        [observation("/root/A.zip"), observation("/copy/A.zip")],
        visible_paths={"/root/A.zip", "/copy/A.zip"},
        now=NOW,
    )

    assert result[0].resource_id == "r_old"
    assert result[1].resource_id != "r_old"
    assert result[1].resource_id.startswith("r_")
    assert repository.commit_count == 1


async def test_application_resolver_ambiguous_match_emits_warning():
    repository = MemoryRepository(
        [
            existing("r_b", "/old/B.zip"),
            existing("r_a", "/old/A.zip"),
        ]
    )
    audit = RecordingAuditSink()

    result = await resolve_resource_identities(
        repository,
        audit,
        [observation("/new/A.zip")],
        visible_paths={"/new/A.zip"},
        now=NOW,
    )

    assert result[0].match_type == "ambiguous_new"
    assert result[0].ambiguous_resource_ids == ["r_a", "r_b"]
    assert ("WARNING", "identity_candidate_ambiguous") == audit.events[-1][0:2]
