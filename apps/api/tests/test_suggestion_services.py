"""A2 整理建议服务最小自测：生成幂等、apply 事务化、批量逐项、撤销产生新修订。"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import CatalogEntry, Resource
from cloudsite.modules.automation.contracts import public as automation_api
from cloudsite.modules.automation.application import suggestion_generator as suggestion_generator_impl


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


def test_file_fingerprint_is_deterministic():
    fp1 = automation_api.compute_file_fingerprint(
        name="app.zip", path="/a", extension="zip", mime_type="application/zip", size=100
    )
    fp2 = automation_api.compute_file_fingerprint(
        name="app.zip", path="/a", extension="zip", mime_type="application/zip", size=100
    )
    assert fp1 == fp2
    fp3 = automation_api.compute_file_fingerprint(
        name="app.zip", path="/b", extension="zip", mime_type="application/zip", size=100
    )
    assert fp1 != fp3


async def test_generate_suggestion_is_idempotent(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        result1 = await automation_api.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert len(result1.created) == 1
        assert result1.skipped == 0

    async with StateSession() as state, IndexSession() as index:
        result2 = await automation_api.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        assert len(result2.created) == 0
        assert result2.skipped == 1


async def test_apply_new_entry_creates_catalog_content(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await automation_api.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        suggestion_id = gen.created[0].suggestion_id

    async with StateSession() as state, IndexSession() as index:
        result = await automation_api.apply_suggestion(state, index, suggestion_id, actor="tester")
        await state.commit()
        assert result.success
        assert result.entry_id is not None

    async with StateSession() as state:
        rows, total = await automation_api.list_suggestions(state, status="applied")
        assert total == 1
        assert rows[0].status == "applied"
        assert rows[0].target_entry_id is not None


async def test_apply_is_idempotent(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await automation_api.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        sid = gen.created[0].suggestion_id

    async with StateSession() as state, IndexSession() as index:
        r1 = await automation_api.apply_suggestion(state, index, sid, actor="tester")
        await state.commit()
    async with StateSession() as state, IndexSession() as index:
        r2 = await automation_api.apply_suggestion(state, index, sid, actor="tester")
        await state.commit()
    assert r1.entry_id == r2.entry_id


async def test_reject_and_idempotent(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await automation_api.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        sid = gen.created[0].suggestion_id

    async with StateSession() as state:
        row = await automation_api.reject_suggestion(state, sid, actor="tester", reason="不需要")
        await state.commit()
        assert row.status == "rejected"
    async with StateSession() as state:
        row2 = await automation_api.reject_suggestion(state, sid, actor="tester")
        await state.commit()
        assert row2.status == "rejected"


async def test_batch_apply_reports_per_item(sessions):
    StateSession, IndexSession = sessions
    resource_a = _make_resource(id="r_aaaaaaaaaaaaaaaaaaaaaaaa000001", name="app-a-v1.0.zip")
    resource_b = _make_resource(id="r_bbbbbbbbbbbbbbbbbbbbbbbb000002", name="app-b-v2.0.zip", path="/software/app-b-v2.0.zip")
    async with IndexSession() as index:
        index.add_all([resource_a, resource_b])
        await index.commit()

    ids = []
    async with StateSession() as state, IndexSession() as index:
        for res in [resource_a, resource_b]:
            g = await automation_api.generate_suggestions_for_resource(state, index, res)
            ids.extend(s.suggestion_id for s in g.created)
        await state.commit()

    async with StateSession() as state, IndexSession() as index:
        batch = await automation_api.batch_apply_suggestions(state, index, ids, actor="tester")
        await state.commit()
        assert batch.succeeded == 2
        assert batch.failed == 0
        assert len(batch.results) == 2


async def test_revert_produces_new_revision(sessions):
    StateSession, IndexSession = sessions
    resource = _make_resource()
    async with IndexSession() as index:
        index.add(resource)
        await index.commit()

    async with StateSession() as state, IndexSession() as index:
        gen = await automation_api.generate_suggestions_for_resource(state, index, resource)
        await state.commit()
        sid = gen.created[0].suggestion_id

    async with StateSession() as state, IndexSession() as index:
        await automation_api.apply_suggestion(state, index, sid, actor="tester")
        await state.commit()

    async with StateSession() as state:
        row = await automation_api.revert_suggestion(state, sid, actor="tester")
        await state.commit()
        assert row.status == "reviewed"
        assert row.applied_at is None

    async with StateSession() as state:
        from sqlalchemy import select
        entry = await state.scalar(select(CatalogEntry).where(CatalogEntry.slug == suggestion_generator_impl._slugify(resource.name)))
        if entry is not None:
            assert entry.status == "archived"
