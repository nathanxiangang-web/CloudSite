"""M6 健康检查分级端点测试。

覆盖：
- GET /api/health 存活探针始终 200 healthy。
- GET /api/ready 就绪探针：数据库正常 + AList 正常 → 200 ready。
- GET /api/ready 数据库正常 + AList 离线 → 200 degraded。
- GET /api/ready 数据库不可用 → 503 not_ready。
- /api/ready 已加入匿名白名单（无需登录即可访问）。
- schema v17→v18 迁移新增 health_check_state 表与 health_check_enabled 列，幂等。
"""
import httpx
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, main
from cloudsite.database import StateBase
from cloudsite.models import AListConnection, SiteSettings, SystemSetting
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version


async def _ready_client(monkeypatch):
    """构造内存 state.db + ASGI 客户端，AList 默认未配置（healthy）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with factory() as session:
        session.add(SiteSettings(id=1))
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await session.commit()
    monkeypatch.setattr(main, "StateSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, factory, engine


async def test_health_liveness_always_200(monkeypatch):
    client, _, engine = await _ready_client(monkeypatch)
    async with client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"
    await engine.dispose()


async def test_ready_all_healthy_returns_200_ready(monkeypatch):
    client, _, engine = await _ready_client(monkeypatch)
    async with client:
        res = await client.get("/api/ready")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ready"
        assert body["components"]["database"]["status"] == "healthy"
        assert body["components"]["alist"]["status"] == "healthy"
    await engine.dispose()


async def test_ready_alist_degraded_returns_200_degraded(monkeypatch):
    from cloudsite.routers import health

    client, _, engine = await _ready_client(monkeypatch)

    async def _alist_degraded(state):
        return "degraded", "AList 连接超时"

    monkeypatch.setattr(health, "_check_alist", _alist_degraded)
    async with client:
        res = await client.get("/api/ready")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "degraded"
        assert body["components"]["database"]["status"] == "healthy"
        assert body["components"]["alist"]["status"] == "degraded"
    await engine.dispose()


async def test_ready_database_unavailable_returns_503_not_ready(monkeypatch):
    client, _, engine = await _ready_client(monkeypatch)

    class _BrokenSession:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): raise RuntimeError("state.db locked")
        async def __aexit__(self, *_a): return False

    monkeypatch.setattr(main, "StateSession", _BrokenSession)
    async with client:
        res = await client.get("/api/ready")
        assert res.status_code == 503
        body = res.json()
        assert body["status"] == "not_ready"
        assert body["components"]["database"]["status"] == "unhealthy"
    await engine.dispose()


async def test_ready_anonymous_accessible(monkeypatch):
    """就绪探针无需登录即可访问（匿名白名单）。"""
    client, _, engine = await _ready_client(monkeypatch)
    async with client:
        res = await client.get("/api/ready")
        assert res.status_code == 200
    await engine.dispose()


async def test_v17_to_v18_adds_health_check_state_and_enabled(tmp_path, monkeypatch):
    """空库 init 达到 v18，含 health_check_state 表与 health_check_enabled 列。"""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "health_check_state" in tables
        settings_cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("system_settings")})
        assert "health_check_enabled" in settings_cols

    await state_engine.dispose()
    await index_engine.dispose()


async def test_v17_to_v18_idempotent(tmp_path, monkeypatch):
    """重复 init 保持 v18 稳定，不重复建表/加列。"""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "health_check_state" in tables

    await state_engine.dispose()
    await index_engine.dispose()
