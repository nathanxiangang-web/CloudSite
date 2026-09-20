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

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


class MemoryFolderRepository:
    def __init__(self, records: list[FolderIdentityRecord] | None = None) -> None:
        self.records = {record.folder_id: record for record in records or []}
        self.histories: list[FolderIdentityHistoryRecord] = []
        self.save_count = 0
        self.add_count = 0

    async def list_active(self) -> list[FolderIdentityRecord]:
        return [
            record
            for record in self.records.values()
            if record.status in {"active", "suspected_missing"}
        ]

    async def add(self, record: FolderIdentityRecord) -> None:
        self.records[record.folder_id] = record
        self.add_count += 1

    async def save(self, record: FolderIdentityRecord) -> None:
        assert record.folder_id in self.records
        self.records[record.folder_id] = record
        self.save_count += 1

    async def add_history(self, record: FolderIdentityHistoryRecord) -> None:
        self.histories.append(record)


def obs(path: str, fingerprint: str = "fp", root_mapping_id: int = 1) -> FolderIdentityObservation:
    return FolderIdentityObservation(
        path=path,
        name=path.rsplit("/", 1)[-1],
        root_mapping_id=root_mapping_id,
        fingerprint=fingerprint,
    )


def existing(
    folder_id: str,
    path: str,
    *,
    fingerprint: str = "fp",
    status: str = "active",
    root_mapping_id: int = 1,
) -> FolderIdentityRecord:
    return FolderIdentityRecord(
        folder_id=folder_id,
        current_path=path,
        root_mapping_id=root_mapping_id,
        status=status,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_name=path.rsplit("/", 1)[-1],
        identity_fingerprint=fingerprint,
        created_from="legacy_migration",
        updated_at=NOW,
    )


async def test_folder_exact_path_preserves_id_and_does_not_create_history():
    repo = MemoryFolderRepository([existing("f_one", "/root/A")])
    result = await resolve_folder_identities(
        repo,
        [obs("/root/A")],
        visible_paths={"/root/A"},
        now=NOW,
    )
    assert result[0].folder_id == "f_one"
    assert result[0].match_type == "observed"
    assert repo.save_count == 1
    assert repo.histories == []


async def test_folder_reactivation_preserves_id():
    repo = MemoryFolderRepository(
        [existing("f_one", "/root/A", status="suspected_missing")]
    )
    result = await resolve_folder_identities(
        repo,
        [obs("/root/A")],
        visible_paths={"/root/A"},
        now=NOW,
    )
    assert result[0].match_type == "reactivated"
    assert repo.records["f_one"].status == "active"


async def test_unique_unseen_fingerprint_renames_without_commit_port():
    repo = MemoryFolderRepository([existing("f_one", "/root/A")])
    result = await resolve_folder_identities(
        repo,
        [obs("/root/B")],
        visible_paths={"/root/B"},
        cycle_id=9,
        now=NOW,
    )
    assert result[0].folder_id == "f_one"
    assert result[0].match_type == "rename"
    assert result[0].previous_path == "/root/A"
    assert repo.records["f_one"].current_path == "/root/B"
    assert repo.histories[0].event_type == "rename"
    assert repo.histories[0].cycle_id == 9
    assert not hasattr(repo, "commit_count")


async def test_cross_parent_unique_candidate_is_move():
    repo = MemoryFolderRepository([existing("f_one", "/root/A")])
    result = await resolve_folder_identities(
        repo,
        [obs("/other/A")],
        visible_paths={"/other/A"},
        now=NOW,
    )
    assert result[0].match_type == "move"


async def test_visible_source_is_copy_and_allocates_new_folder_id():
    repo = MemoryFolderRepository([existing("f_old", "/root/A")])
    result = await resolve_folder_identities(
        repo,
        [obs("/copy/A")],
        visible_paths={"/root/A", "/copy/A"},
        now=NOW,
    )
    assert result[0].folder_id != "f_old"
    assert result[0].folder_id.startswith("f_")
    assert result[0].match_type == "created"
    assert repo.add_count == 1


async def test_multiple_candidates_are_ambiguous_new():
    repo = MemoryFolderRepository(
        [
            existing("f_a", "/old/A"),
            existing("f_b", "/old/B"),
        ]
    )
    result = await resolve_folder_identities(
        repo,
        [obs("/new/A")],
        visible_paths={"/new/A"},
        now=NOW,
    )
    assert result[0].match_type == "ambiguous"
    assert result[0].folder_id not in {"f_a", "f_b"}


async def test_root_mapping_must_match_for_fingerprint_reuse():
    repo = MemoryFolderRepository(
        [existing("f_one", "/root/A", root_mapping_id=2)]
    )
    result = await resolve_folder_identities(
        repo,
        [obs("/root/B", root_mapping_id=1)],
        visible_paths={"/root/B"},
        now=NOW,
    )
    assert result[0].match_type == "created"
    assert result[0].folder_id != "f_one"
