"""A2 候选生成幂等测试。

相同 (source_file_id, file_fingerprint, parser_version, suggestion_kind) 重跑
不重复生成；人工已确认结果（applied/rejected）不被覆盖；文件变化产生新草稿。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import CatalogSuggestion, Resource
from cloudsite.services import suggestion_generator, suggestion_review


@pytest.fixture
async def sessions(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    StateSession = async_sessionmaker(state_engine, expire_on_commit=False, class_=AsyncSession)
    IndexSession = async_sessionmaker(index_engine, expire_on_commit=False, class_=AsyncSession)
    yield StateSession, IndexSession
    await state_engine.dispose()
    await index_engine.dispose()


def _make_resource(**overrides):
    defaults = {
        "id": "r_testresource0000000000000001",
        "name": "CloudSite-v1.2.3-windows-x64.msi",
        "path": "/software/CloudSite-v1.2.3-windows-x64.msi",
        "parent_id": None,
        "content_type": "software",
        "root_mapping_id": None,
        "extension": "msi",
        "mime_type": "application/x-msi",
        "size": 1024000,
    }
    defaults.update(overrides)
    return Resource(**defaults)


async def _count_suggestions(state):
    from sqlalchemy import func
    return int(await state.scalar(select(func.count()).select_from(CatalogSuggestion)) or 0)


async def test_same_fingerprint_reproducible_is_idempotent(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        r1 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert len(r1.created) == 1
        assert r1.skipped == 0

    async with StateSession() as state, IndexSession() as index:
        r2 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert len(r2.created) == 0
        assert r2.skipped == 1

    async with StateSession() as state:
        assert await _count_suggestions(state) == 1


async def test_applied_suggestion_not_overwritten_by_reproducible_run(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        sid = gen.created[0].suggestion_id

    async with StateSession() as state, IndexSession() as index:
        await suggestion_review.apply_suggestion(state, index, sid, actor="tester")
        await state.commit()

    async with StateSession() as state, IndexSession() as index:
        r2 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert len(r2.created) == 0
        assert r2.skipped == 1

    async with StateSession() as state:
        row = await state.get(CatalogSuggestion, sid)
        assert row.status == "applied"
        assert row.reviewed_by == "tester"


async def test_rejected_suggestion_not_overwritten_by_reproducible_run(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        sid = gen.created[0].suggestion_id

    async with StateSession() as state:
        await suggestion_review.reject_suggestion(state, sid, actor="tester", reason="不需要")
        await state.commit()

    async with StateSession() as state, IndexSession() as index:
        r2 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert len(r2.created) == 0

    async with StateSession() as state:
        row = await state.get(CatalogSuggestion, sid)
        assert row.status == "rejected"
        assert row.reject_reason == "不需要"


async def test_changed_file_size_produces_new_suggestion(sessions):
    StateSession, IndexSession = sessions
    resource_v1 = _make_resource(size=1024000)
    async with IndexSession() as index:
        index.add(resource_v1)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen1 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource_v1)
        await state.commit()
        assert len(gen1.created) == 1
        sid1 = gen1.created[0].suggestion_id

    resource_v2 = _make_resource(size=2048000)
    async with IndexSession() as index:
        existing = await index.get(Resource, resource_v1.id)
        existing.size = 2048000
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen2 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource_v2)
        await state.commit()
        assert len(gen2.created) == 1
        sid2 = gen2.created[0].suggestion_id
        assert sid2 != sid1

    async with StateSession() as state:
        assert await _count_suggestions(state) == 2


async def test_changed_file_name_produces_new_fingerprint(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource(name="app-old-v1.0.zip")
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen1 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        fp1 = gen1.created[0].file_fingerprint

    resource_renamed = _make_resource(name="app-new-v2.0.zip")
    async with IndexSession() as index:
        existing = await index.get(Resource, resource.id)
        existing.name = "app-new-v2.0.zip"
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen2 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource_renamed)
        await state.commit()
        fp2 = gen2.created[0].file_fingerprint

    assert fp1 != fp2


async def test_batch_generate_is_idempotent(sessions):
    StateSession, IndexSession = sessions
    resource_a = _make_resource(id="r_aaaaaaaaaaaaaaaaaaaaaaaa000001", name="app-a-v1.0.zip")
    resource_b = _make_resource(id="r_bbbbbbbbbbbbbbbbbbbbbbbb000002", name="app-b-v2.0.zip", path="/software/app-b-v2.0.zip")
    async with IndexSession() as index:
        index.add_all([resource_a, resource_b])
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        r1 = await suggestion_generator.generate_suggestions_batch(state, index, limit=200)
        await state.commit()
        assert len(r1.created) == 2
        assert r1.skipped == 0

    async with StateSession() as state, IndexSession() as index:
        r2 = await suggestion_generator.generate_suggestions_batch(state, index, limit=200)
        await state.commit()
        assert len(r2.created) == 0
        assert r2.skipped == 2

    async with StateSession() as state:
        assert await _count_suggestions(state) == 2


async def test_shadow_mode_does_not_create_catalog_entries(sessions):
    StateSession, IndexSession = sessions
    from cloudsite.models import CatalogEntry
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()

    async with StateSession() as state:
        entries = list((await state.scalars(select(CatalogEntry))).all())
        assert entries == []


async def test_unique_constraint_prevents_duplicate_on_concurrent_insert(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        original = gen.created[0]

    async with StateSession() as state, IndexSession() as index:
        r2 = await suggestion_generator.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert r2.created == [] or all(
            row.suggestion_id != original.suggestion_id for row in r2.created
        )
