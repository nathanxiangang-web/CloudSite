"""8.4 单元测试：apply_search_fts_delta 行级操作"""
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase
from cloudsite.models import Folder, Resource
from cloudsite.search import FtsDeltaOp, apply_search_fts_delta


async def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, tokenize='unicode61 remove_diacritics 2')"
        )
    return engine, factory


async def _fts_count(session):
    return int(await session.scalar(text("SELECT COUNT(*) FROM search_fts")))


async def test_insert_op():
    engine, factory = await _make_factory()
    async with factory() as session:
        op = FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="test", extension="txt", content_type="file", breadcrumb_text="/root/test.txt")
        result = await apply_search_fts_delta(session, [op])
        assert result["applied"] == 1
        assert result["failed"] == 0
        assert await _fts_count(session) == 1
    await engine.dispose()


async def test_update_op_replaces_row():
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="old", extension="", content_type="file", breadcrumb_text="/root/old")])
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="update", object_id="r1", object_type="resource", name="new", extension="txt", content_type="file", breadcrumb_text="/root/new.txt")])
        assert await _fts_count(session) == 1
        row = (await session.execute(text("SELECT name, breadcrumb_text FROM search_fts WHERE object_id='r1'"))).fetchone()
        assert row[0] == "new"
        assert row[1] == "/root/new.txt"
    await engine.dispose()


async def test_delete_op_removes_row():
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="test", content_type="file", breadcrumb_text="/root/test")])
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="delete", object_id="r1", object_type="resource")])
        assert await _fts_count(session) == 0
    await engine.dispose()


async def test_rename_cascade_updates_breadcrumb_prefix():
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="insert", object_id="f1", object_type="folder", name="foo", content_type="software", breadcrumb_text="/root/foo"),
            FtsDeltaOp(op_type="insert", object_id="f2", object_type="folder", name="sub", content_type="software", breadcrumb_text="/root/foo/sub"),
            FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="file.txt", content_type="software", breadcrumb_text="/root/foo/sub/file.txt"),
        ])
        result = await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="update", object_id="f1", object_type="folder", name="bar", content_type="software", breadcrumb_text="/root/bar"),
            FtsDeltaOp(op_type="rename_cascade", object_id="", object_type="folder", old_path_prefix="/root/foo", new_path_prefix="/root/bar"),
        ])
        assert result["applied"] == 2
        assert result["failed"] == 0

        rows = (await session.execute(text("SELECT object_id, breadcrumb_text FROM search_fts ORDER BY breadcrumb_text"))).fetchall()
        paths = [r[1] for r in rows]
        assert "/root/bar" in paths
        assert "/root/bar/sub" in paths
        assert "/root/bar/sub/file.txt" in paths
        assert not any("/root/foo" in p for p in paths)
    await engine.dispose()


async def test_failed_op_marks_dirty(monkeypatch):
    engine, factory = await _make_factory()
    async with factory() as session:
        op = FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="test", content_type="file", breadcrumb_text="/root/test")
        original_execute = session.execute

        call_count = 0
        async def failing_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated failure")
            return await original_execute(*args, **kwargs)

        monkeypatch.setattr(session, "execute", failing_execute)
        result = await apply_search_fts_delta(session, [op])
        assert result["failed"] >= 1
    await engine.dispose()


async def test_partial_failure_preserves_prior_ops(monkeypatch):
    from cloudsite import search as search_mod
    async def noop_dirty(_dirty):
        return None
    monkeypatch.setattr(search_mod, "set_search_index_dirty", noop_dirty)
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="a", content_type="file", breadcrumb_text="/root/a")])
        count_before = await _fts_count(session)
        original_execute = session.execute
        async def failing(*a, **k):
            raise RuntimeError("fail")
        monkeypatch.setattr(session, "execute", failing)
        result = await apply_search_fts_delta(session, [FtsDeltaOp(op_type="insert", object_id="r2", object_type="resource", name="b", content_type="file", breadcrumb_text="/root/b")])
        assert result["failed"] >= 1
        monkeypatch.setattr(session, "execute", original_execute)
        assert await _fts_count(session) == count_before
    await engine.dispose()

async def test_insert_preserves_description_and_tags():
    engine, factory = await _make_factory()
    async with factory() as session:
        op = FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="test", extension="txt", content_type="file", description="my desc", tags="tag1,tag2", breadcrumb_text="/root/test.txt")
        await apply_search_fts_delta(session, [op])
        row = (await session.execute(text("SELECT description, tags FROM search_fts WHERE object_id='r1'"))).fetchone()
        assert row[0] == "my desc"
        assert row[1] == "tag1,tag2"
    await engine.dispose()


async def test_update_preserves_description_and_tags():
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="old", content_type="file", description="old desc", tags="old", breadcrumb_text="/root/old")])
        await apply_search_fts_delta(session, [FtsDeltaOp(op_type="update", object_id="r1", object_type="resource", name="new", content_type="file", description="new desc", tags="new", breadcrumb_text="/root/new")])
        row = (await session.execute(text("SELECT description, tags FROM search_fts WHERE object_id='r1'"))).fetchone()
        assert row[0] == "new desc"
        assert row[1] == "new"
    await engine.dispose()


async def test_rename_cascade_preserves_description_and_tags():
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="insert", object_id="f1", object_type="folder", name="foo", content_type="software", description="foo desc", tags="foo", breadcrumb_text="/root/foo"),
            FtsDeltaOp(op_type="insert", object_id="f2", object_type="folder", name="sub", content_type="software", description="sub desc", tags="sub", breadcrumb_text="/root/foo/sub"),
        ])
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="rename_cascade", object_id="", object_type="folder", old_path_prefix="/root/foo", new_path_prefix="/root/bar"),
        ])
        rows = (await session.execute(text("SELECT object_id, description, tags, breadcrumb_text FROM search_fts WHERE breadcrumb_text LIKE '/root/bar%' ORDER BY breadcrumb_text"))).fetchall()
        assert any(r[1] == "sub desc" and r[2] == "sub" and r[3] == "/root/bar/sub" for r in rows)
    await engine.dispose()


async def test_insert_is_idempotent_on_duplicate_object_id():
    engine, factory = await _make_factory()
    async with factory() as session:
        op = FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="test", content_type="file", breadcrumb_text="/root/test")
        await apply_search_fts_delta(session, [op])
        await apply_search_fts_delta(session, [op])
        assert await _fts_count(session) == 1
    await engine.dispose()


async def test_rename_cascade_underscore_does_not_match_axb():
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="insert", object_id="f1", object_type="folder", name="a_b", content_type="software", breadcrumb_text="/a_b"),
            FtsDeltaOp(op_type="insert", object_id="f2", object_type="folder", name="sub", content_type="software", breadcrumb_text="/a_b/sub"),
            FtsDeltaOp(op_type="insert", object_id="faxb", object_type="folder", name="axb", content_type="software", breadcrumb_text="/axb"),
            FtsDeltaOp(op_type="insert", object_id="faxby", object_type="folder", name="y", content_type="software", breadcrumb_text="/axb/y"),
        ])
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="rename_cascade", object_id="", object_type="folder", old_path_prefix="/a_b", new_path_prefix="/new"),
        ])
        rows = (await session.execute(text("SELECT breadcrumb_text FROM search_fts ORDER BY breadcrumb_text"))).fetchall()
        paths = [r[0] for r in rows]
        assert "/new/sub" in paths
        assert "/axb" in paths
        assert "/axb/y" in paths
        assert not any(p.startswith("/a_b/") for p in paths)
    await engine.dispose()


async def test_rename_cascade_percent_does_not_match_other(monkeypatch):
    engine, factory = await _make_factory()
    async with factory() as session:
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="insert", object_id="f1", object_type="folder", name="a%", content_type="software", breadcrumb_text="/a%"),
            FtsDeltaOp(op_type="insert", object_id="f2", object_type="folder", name="d", content_type="software", breadcrumb_text="/a%/d"),
            FtsDeltaOp(op_type="insert", object_id="fab", object_type="folder", name="ab", content_type="software", breadcrumb_text="/ab"),
            FtsDeltaOp(op_type="insert", object_id="fabc", object_type="folder", name="c", content_type="software", breadcrumb_text="/ab/c"),
        ])
        await apply_search_fts_delta(session, [
            FtsDeltaOp(op_type="rename_cascade", object_id="", object_type="folder", old_path_prefix="/a%", new_path_prefix="/newp"),
        ])
        rows = (await session.execute(text("SELECT breadcrumb_text FROM search_fts ORDER BY breadcrumb_text"))).fetchall()
        paths = [r[0] for r in rows]
        assert "/newp/d" in paths
        assert "/ab" in paths
        assert "/ab/c" in paths
        assert not any(p.startswith("/a%/") for p in paths)
    await engine.dispose()


async def test_delta_failure_sets_dirty_true(monkeypatch):
    from cloudsite import search as search_mod
    dirty_calls = []
    async def capture_dirty(d):
        dirty_calls.append(d)
    monkeypatch.setattr(search_mod, "set_search_index_dirty", capture_dirty)
    engine, factory = await _make_factory()
    async with factory() as session:
        original_execute = session.execute
        call_count = 0
        async def failing_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated")
            return await original_execute(*args, **kwargs)
        monkeypatch.setattr(session, "execute", failing_execute)
        op = FtsDeltaOp(op_type="insert", object_id="r1", object_type="resource", name="t", content_type="file", breadcrumb_text="/t")
        result = await apply_search_fts_delta(session, [op])
        assert result["failed"] >= 1
        assert True in dirty_calls
    await engine.dispose()
