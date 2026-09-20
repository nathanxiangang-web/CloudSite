"""R4 PR01: Identity matching engine tests (V2 doc 22-23).

Exercises the pure IdentityMatchingEngine (fingerprint extraction, matching,
conflict detection, rename/move/subtree id preservation, cross-root
non-support) and the IdentityRepository persistence over a temporary SQLite
database created via text-based SQL (no cloudsite.models imports).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cloudsite.modules.indexing.domain.identity import (
    IdentityFingerprint,
    IdentityMatchingEngine,
    IdentityRecord,
)
from cloudsite.modules.indexing.infrastructure.identity_repository import (
    IdentityRepository,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


@dataclass(slots=True)
class Entry:
    name: str
    size: int | None
    modified_at: datetime | None
    root_mapping_id: int
    path: str | None = None


def _entry(
    name: str = "A.zip",
    size: int = 1024,
    modified_at: datetime | None = NOW,
    root_mapping_id: int = 1,
    path: str | None = None,
) -> Entry:
    return Entry(
        name=name,
        size=size,
        modified_at=modified_at,
        root_mapping_id=root_mapping_id,
        path=path if path is not None else f"/root/{name}",
    )


def _history_record(
    resource_id: str,
    fingerprint: IdentityFingerprint,
    *,
    status: str = "active",
) -> IdentityRecord:
    return IdentityRecord(
        resource_id=resource_id,
        fingerprint=fingerprint.digest,
        root_mapping_id=fingerprint.root_mapping_id,
        name=fingerprint.name,
        path=fingerprint.path,
        size=fingerprint.size,
        modified_at=fingerprint.modified_at,
        first_seen_at=NOW,
        last_seen_at=NOW,
        status=status,
    )


def test_fingerprint_extraction():
    engine = IdentityMatchingEngine()
    entry = _entry(name="report.pdf", size=2048, modified_at=NOW, root_mapping_id=7, path="/root/sub/report.pdf")
    fp = engine.extract_fingerprint(entry)
    assert fp.name == "report.pdf"
    assert fp.size == 2048
    assert fp.modified_at == NOW
    assert fp.root_mapping_id == 7
    assert fp.path == "/root/sub/report.pdf"
    assert fp.digest
    assert fp.digest != ""


def test_fingerprint_digest_is_name_and_path_independent():
    engine = IdentityMatchingEngine()
    base = engine.extract_fingerprint(_entry(name="A.zip", size=100, path="/root/A.zip"))
    renamed = engine.extract_fingerprint(_entry(name="B.zip", size=100, path="/root/B.zip"))
    moved = engine.extract_fingerprint(_entry(name="A.zip", size=100, path="/other/A.zip"))
    assert base.digest == renamed.digest
    assert base.digest == moved.digest


def test_match_same_fingerprint_same_id():
    engine = IdentityMatchingEngine()
    fp = engine.extract_fingerprint(_entry())
    history = [_history_record("res-1", fp)]
    result = engine.match(fp, history)
    assert result.is_matched
    assert result.resource_id == "res-1"
    assert result.previous_path == fp.path


def test_match_no_history():
    engine = IdentityMatchingEngine()
    fp = engine.extract_fingerprint(_entry())
    result = engine.match(fp, [])
    assert result.is_new
    assert result.resource_id is None


def test_match_multiple_conflict():
    engine = IdentityMatchingEngine()
    fp = engine.extract_fingerprint(_entry(size=500))
    history = [
        _history_record("res-a", fp, status="active"),
        _history_record("res-b", fp, status="active"),
    ]
    result = engine.match(fp, history)
    assert result.is_conflict
    assert result.resource_id is None
    assert set(result.conflicting_ids) == {"res-a", "res-b"}


def test_conflict_not_silently_matched():
    engine = IdentityMatchingEngine()
    fp = engine.extract_fingerprint(_entry(size=500))
    history = [
        _history_record("res-a", fp),
        _history_record("res-b", fp),
        _history_record("res-c", fp),
    ]
    result = engine.match(fp, history)
    assert result.is_conflict
    assert result.resource_id is None
    assert len(result.conflicting_ids) == 3
    assert result.match_type != "matched"


def test_file_rename_preserves_id():
    engine = IdentityMatchingEngine()
    original = engine.extract_fingerprint(_entry(name="A.zip", size=4096, path="/root/A.zip"))
    history = [_history_record("res-A", original)]
    renamed = engine.extract_fingerprint(_entry(name="B.zip", size=4096, path="/root/B.zip"))
    result = engine.match(renamed, history)
    assert result.is_matched
    assert result.resource_id == "res-A"
    assert result.previous_path == "/root/A.zip"


def test_file_move_preserves_id():
    engine = IdentityMatchingEngine()
    original = engine.extract_fingerprint(_entry(name="A.zip", size=4096, path="/root/A.zip"))
    history = [_history_record("res-A", original)]
    moved = engine.extract_fingerprint(_entry(name="A.zip", size=4096, path="/root/sub/A.zip"))
    result = engine.match(moved, history)
    assert result.is_matched
    assert result.resource_id == "res-A"


def test_folder_rename_preserves_descendant_ids():
    engine = IdentityMatchingEngine()
    descendants = [
        ("a.txt", 10, "/docs/a.txt"),
        ("b.txt", 20, "/docs/b.txt"),
        ("c.txt", 30, "/docs/c.txt"),
    ]
    history = [
        _history_record(f"res-{name}", engine.extract_fingerprint(_entry(name=name, size=size, path=path)))
        for name, size, path in descendants
    ]
    renamed = [
        engine.extract_fingerprint(
            _entry(name=name, size=size, path=path.replace("/docs/", "/documents/", 1))
        )
        for name, size, path in descendants
    ]
    for (name, _size, _path), fp in zip(descendants, renamed):
        result = engine.match(fp, history)
        assert result.is_matched, f"descendant {name} should preserve id"
        assert result.resource_id == f"res-{name}"


def test_subtree_path_update():
    engine = IdentityMatchingEngine()
    original = engine.extract_fingerprint(_entry(name="x.txt", size=99, path="/a/b/x.txt"))
    history = [_history_record("res-x", original)]
    updated = engine.extract_fingerprint(_entry(name="x.txt", size=99, path="/a/c/b/x.txt"))
    result = engine.match(updated, history)
    assert result.is_matched
    assert result.resource_id == "res-x"


def test_cross_root_move_not_supported():
    engine = IdentityMatchingEngine()
    original = engine.extract_fingerprint(_entry(name="A.zip", size=4096, root_mapping_id=1, path="/root1/A.zip"))
    history = [_history_record("res-A", original)]
    cross_root = engine.extract_fingerprint(_entry(name="A.zip", size=4096, root_mapping_id=2, path="/root2/A.zip"))
    result = engine.match(cross_root, history)
    assert result.is_new
    assert result.resource_id is None


def test_record_history_builds_correct_record():
    engine = IdentityMatchingEngine()
    fp = engine.extract_fingerprint(_entry(name="A.zip", size=128, path="/root/A.zip"))
    record = engine.record_history("res-1", fp, now=NOW)
    assert record.resource_id == "res-1"
    assert record.fingerprint == fp.digest
    assert record.root_mapping_id == fp.root_mapping_id
    assert record.name == "A.zip"
    assert record.path == "/root/A.zip"
    assert record.size == 128
    assert record.first_seen_at == NOW
    assert record.last_seen_at == NOW
    assert record.status == "active"


async def _make_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'identity.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def test_identity_history_recorded(tmp_path):
    engine_db, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            repo = IdentityRepository(session)
            await repo.ensure_table()
            engine = IdentityMatchingEngine()
            fp = engine.extract_fingerprint(_entry(name="A.zip", size=256, path="/root/A.zip"))
            await repo.save("res-1", fp, now=NOW)
            await session.commit()

        async with factory() as session:
            repo = IdentityRepository(session)
            record = await repo.find_by_resource_id("res-1")
            assert record is not None
            assert record.resource_id == "res-1"
            assert record.fingerprint == fp.digest
            assert record.root_mapping_id == 1
            assert record.name == "A.zip"
            assert record.path == "/root/A.zip"
            assert record.size == 256
            assert record.status == "active"
    finally:
        await engine_db.dispose()


async def test_identity_history_query(tmp_path):
    engine_db, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            repo = IdentityRepository(session)
            await repo.ensure_table()
            engine = IdentityMatchingEngine()
            fp_a = engine.extract_fingerprint(_entry(name="A.zip", size=100, path="/root/A.zip"))
            fp_b = engine.extract_fingerprint(_entry(name="B.zip", size=200, path="/root/B.zip"))
            await repo.save("res-A", fp_a, now=NOW)
            await repo.save("res-B", fp_b, now=NOW)
            await session.commit()

        async with factory() as session:
            repo = IdentityRepository(session)
            matches = await repo.find_by_fingerprint(fp_a)
            assert len(matches) == 1
            assert matches[0].resource_id == "res-A"

            matches_b = await repo.find_by_fingerprint(fp_b)
            assert len(matches_b) == 1
            assert matches_b[0].resource_id == "res-B"

            none = await repo.find_by_fingerprint(
                engine.extract_fingerprint(_entry(name="C.zip", size=999, path="/root/C.zip"))
            )
            assert none == []

        async with factory() as session:
            repo = IdentityRepository(session)
            await repo.delete_by_resource_id("res-A")
            await session.commit()

        async with factory() as session:
            repo = IdentityRepository(session)
            assert await repo.find_by_resource_id("res-A") is None
            assert await repo.find_by_resource_id("res-B") is not None
    finally:
        await engine_db.dispose()


async def test_identity_history_upsert_preserves_id_on_path_change(tmp_path):
    engine_db, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            repo = IdentityRepository(session)
            await repo.ensure_table()
            engine = IdentityMatchingEngine()
            original = engine.extract_fingerprint(_entry(name="A.zip", size=512, path="/root/A.zip"))
            await repo.save("res-A", original, now=NOW)
            await session.commit()

        async with factory() as session:
            repo = IdentityRepository(session)
            moved = engine.extract_fingerprint(_entry(name="A.zip", size=512, path="/root/sub/A.zip"))
            await repo.save("res-A", moved, now=NOW)
            await session.commit()

        async with factory() as session:
            repo = IdentityRepository(session)
            record = await repo.find_by_resource_id("res-A")
            assert record is not None
            assert record.path == "/root/sub/A.zip"
            assert record.fingerprint == moved.digest
            assert record.fingerprint == original.digest
    finally:
        await engine_db.dispose()
