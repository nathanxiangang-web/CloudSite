"""Folder identity repository/application port tests."""

from datetime import datetime, timezone

from cloudsite.modules.identity.application.folder_resolution import (
    resolve_folder_identities,
)
from cloudsite.modules.identity.domain.models import FolderIdentityObservation
from cloudsite.modules.identity.domain.records import (
    FolderIdentityHistoryRecord,
    FolderIdentityRecord,
)


NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


class MemoryFolderRepository:
    def __init__(self, records: list[FolderIdentityRecord] | None = None) -> None:
        self.records = {record.folder_id: record for record in records or []}
        self.histories: list[FolderIdentityHistoryRecord] = []
        self.commit_called = False

    async def list_active_candidates(self) -> list[FolderIdentityRecord]:
        return [
            record
            for record in self.records.values()
            if record.status in {"active", "suspected_missing"}
        ]

    async def add(self, record: FolderIdentityRecord) -> None:
        self.records[record.folder_id] = record

    async def save(self, record: FolderIdentityRecord) -> None:
        assert record.folder_id in self.records
        self.records[record.folder_id] = record

    async def add_history(self, record: FolderIdentityHistoryRecord) -> None:
        self.histories.append(record)

    async def commit(self) -> None:
        self.commit_called = True
        raise AssertionError("folder resolver must never own commit")


def observation(path: str, fingerprint: str = "fp") -> FolderIdentityObservation:
    return FolderIdentityObservation(
        path=path,
        name=path.rsplit("/", 1)[-1],
        root_mapping_id=1,
        fingerprint=fingerprint,
    )


def existing(folder_id: str, path: str, fingerprint: str = "fp") -> FolderIdentityRecord:
    return FolderIdentityRecord(
        folder_id=folder_id,
        current_path=path,
        root_mapping_id=1,
        status="active",
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_name=path.rsplit("/", 1)[-1],
        identity_fingerprint=fingerprint,
        created_from="new_folder",
        updated_at=NOW,
    )


async def test_folder_application_rename_records_history_without_commit():
    repository = MemoryFolderRepository([existing("f_old", "/root/old")])

    result = await resolve_folder_identities(
        repository,
        [observation("/root/new")],
        visible_paths={"/root/new"},
        now=NOW,
    )

    assert result[0].folder_id == "f_old"
    assert result[0].match_type == "rename"
    assert repository.records["f_old"].current_path == "/root/new"
    assert repository.histories[0].event_type == "rename"
    assert repository.commit_called is False


async def test_folder_application_cross_root_candidate_is_not_reused():
    record = existing("f_old", "/root/old")
    record.root_mapping_id = 2
    repository = MemoryFolderRepository([record])

    result = await resolve_folder_identities(
        repository,
        [observation("/root/new")],
        visible_paths={"/root/new"},
        now=NOW,
    )

    assert result[0].folder_id != "f_old"
    assert result[0].match_type == "created"
    assert repository.commit_called is False


async def test_folder_application_multiple_candidates_is_ambiguous_new():
    repository = MemoryFolderRepository(
        [
            existing("f_a", "/root/a"),
            existing("f_b", "/root/b"),
        ]
    )

    result = await resolve_folder_identities(
        repository,
        [observation("/root/c")],
        visible_paths={"/root/c"},
        now=NOW,
    )

    assert result[0].folder_id not in {"f_a", "f_b"}
    assert result[0].match_type == "ambiguous"
    assert repository.commit_called is False
