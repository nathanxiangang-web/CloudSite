"""X1 连接管理服务测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import AListConnection, ContentRootMapping, ProviderCompatRecord
from cloudsite.services.connections import (
    all_enabled_connections,
    create_connection,
    delete_connection,
    get_connection,
    get_connection_roots,
    list_compat_records,
    list_connections,
    record_compat,
    toggle_connection,
    update_connection,
)


@pytest.fixture
async def session_factory(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    yield factory
    await state_engine.dispose()
    await index_engine.dispose()


@pytest.mark.asyncio
async def test_create_connection(session_factory):
    async with session_factory() as session:
        result = await create_connection(
            session,
            name="第二来源",
            base_url="https://alist2.example.com",
            username="admin",
            password="secret",
        )
        assert result.ok
        assert result.connection_id is not None
        conn = await get_connection(session, result.connection_id)
        assert conn is not None
        assert conn.name == "第二来源"
        assert conn.base_url == "https://alist2.example.com"
        assert conn.enabled is False
        assert conn.password_ciphertext != ""


@pytest.mark.asyncio
async def test_list_connections(session_factory):
    async with session_factory() as session:
        await create_connection(session, name="默认连接", base_url="https://a1.com", username="u", password="p")
        await create_connection(session, name="第二来源", base_url="https://a2.com", username="u", password="p")
        conns = await list_connections(session)
        assert len(conns) == 2


@pytest.mark.asyncio
async def test_update_connection(session_factory):
    async with session_factory() as session:
        result = await create_connection(session, name="conn1", base_url="https://a.com", username="u", password="p")
        update_result = await update_connection(session, result.connection_id, name="renamed", base_url="https://b.com")
        assert update_result.ok
        conn = await get_connection(session, result.connection_id)
        assert conn.name == "renamed"
        assert conn.base_url == "https://b.com"


@pytest.mark.asyncio
async def test_toggle_connection(session_factory):
    async with session_factory() as session:
        result = await create_connection(session, name="conn1", base_url="https://a.com", username="u", password="p")
        toggle_result = await toggle_connection(session, result.connection_id, True)
        assert toggle_result.ok
        conn = await get_connection(session, result.connection_id)
        assert conn.enabled is True
        enabled_conns = await all_enabled_connections(session)
        assert len(enabled_conns) == 1


@pytest.mark.asyncio
async def test_delete_connection(session_factory):
    async with session_factory() as session:
        await create_connection(session, name="conn0", base_url="https://a0.com", username="u", password="p")
        result = await create_connection(session, name="conn1", base_url="https://a.com", username="u", password="p")
        del_result = await delete_connection(session, result.connection_id)
        assert del_result.ok
        conn = await get_connection(session, result.connection_id)
        assert conn is None


@pytest.mark.asyncio
async def test_delete_default_connection_blocked(session_factory):
    async with session_factory() as session:
        session.add(AListConnection(id=1, name="默认", base_url="https://a.com", username="u", password_ciphertext="x", enabled=True))
        await session.commit()
        result = await delete_connection(session, 1)
        assert not result.ok
        assert "不可删除" in result.message


@pytest.mark.asyncio
async def test_delete_connection_with_roots_blocked(session_factory):
    async with session_factory() as session:
        await create_connection(session, name="conn0", base_url="https://a0.com", username="u", password="p")
        result = await create_connection(session, name="conn1", base_url="https://a.com", username="u", password="p")
        session.add(ContentRootMapping(connection_id=result.connection_id, content_type="software", display_name="test", alist_path="/test"))
        await session.commit()
        del_result = await delete_connection(session, result.connection_id)
        assert not del_result.ok
        assert "内容根映射" in del_result.message


@pytest.mark.asyncio
async def test_connection_roots(session_factory):
    async with session_factory() as session:
        result = await create_connection(session, name="conn1", base_url="https://a.com", username="u", password="p")
        session.add(ContentRootMapping(connection_id=result.connection_id, content_type="software", display_name="root1", alist_path="/path1", enabled=True))
        session.add(ContentRootMapping(connection_id=result.connection_id, content_type="video", display_name="root2", alist_path="/path2", enabled=True))
        session.add(ContentRootMapping(connection_id=result.connection_id, content_type="music", display_name="root3", alist_path="/path3", enabled=False))
        await session.commit()
        roots = await get_connection_roots(session, result.connection_id)
        assert len(roots) == 2


@pytest.mark.asyncio
async def test_multi_connection_same_path_no_collision(session_factory):
    """验收：两个来源同路径不碰撞。"""
    async with session_factory() as session:
        r1 = await create_connection(session, name="conn1", base_url="https://a1.com", username="u", password="p")
        r2 = await create_connection(session, name="conn2", base_url="https://a2.com", username="u", password="p")
        session.add(ContentRootMapping(connection_id=r1.connection_id, content_type="software", display_name="root-a", alist_path="/shared/path"))
        session.add(ContentRootMapping(connection_id=r2.connection_id, content_type="software", display_name="root-b", alist_path="/shared/path"))
        await session.commit()
        roots1 = await get_connection_roots(session, r1.connection_id)
        roots2 = await get_connection_roots(session, r2.connection_id)
        assert len(roots1) == 1
        assert len(roots2) == 1
        assert roots1[0].alist_path == "/shared/path"
        assert roots2[0].alist_path == "/shared/path"


@pytest.mark.asyncio
async def test_disable_one_connection_does_not_affect_other(session_factory):
    """验收：禁用一个来源不影响另一个。"""
    async with session_factory() as session:
        r1 = await create_connection(session, name="conn1", base_url="https://a1.com", username="u", password="p")
        r2 = await create_connection(session, name="conn2", base_url="https://a2.com", username="u", password="p")
        await toggle_connection(session, r1.connection_id, True)
        await toggle_connection(session, r2.connection_id, True)
        await toggle_connection(session, r1.connection_id, False)
        enabled = await all_enabled_connections(session)
        assert len(enabled) == 1
        assert enabled[0].id == r2.connection_id


@pytest.mark.asyncio
async def test_record_and_list_compat(session_factory):
    """验收：所有支持平台有实际兼容记录。"""
    async with session_factory() as session:
        await record_compat(
            session,
            provider_type="generic_alist",
            adapter_version="generic_alist@1",
            platform="alist-v3",
            platform_version="3.25.0",
            test_result="pass",
            notes="list/download/preview 正常",
        )
        await record_compat(
            session,
            provider_type="generic_alist",
            adapter_version="generic_alist@1",
            platform="alist-v3",
            platform_version="3.30.0",
            test_result="pass",
        )
        records = await list_compat_records(session)
        assert len(records) == 2
        assert all(r.provider_type == "generic_alist" for r in records)


@pytest.mark.asyncio
async def test_update_nonexistent_connection(session_factory):
    async with session_factory() as session:
        result = await update_connection(session, 999, name="x")
        assert not result.ok


@pytest.mark.asyncio
async def test_toggle_nonexistent_connection(session_factory):
    async with session_factory() as session:
        result = await toggle_connection(session, 999, True)
        assert not result.ok