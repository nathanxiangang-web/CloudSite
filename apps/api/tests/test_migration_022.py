from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.database import IndexBase, StateBase


async def test_021_fixture_upgrade_preserves_user_and_rolling_cycle(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, username_normalized, password_hash, status, created_at, updated_at, created_by_admin) "
                "VALUES (7, 'JC', 'jc', 'argon2-fixture', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            )
        )
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO sync_cycles "
                "(id, cycle_type, status, anchor_at, planned_folder_count, completed_folder_count, "
                "failed_folder_count, carry_over_count, windows_total, windows_completed, "
                "alist_list_requests, changed_scope_count, unchanged_scope_count, fts_rebuilt_count, "
                "created_at, updated_at) "
                "VALUES (11, 'normal', 'running', CURRENT_TIMESTAMP, 20, 8, 1, 2, 4, 1, 33, 4, 4, 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as connection:
        user = (await connection.execute(text("SELECT id, username, password_hash, status FROM users WHERE id = 7"))).one()
    async with index_engine.connect() as connection:
        cycle = (await connection.execute(text("SELECT id, status, completed_folder_count, alist_list_requests FROM sync_cycles WHERE id = 11"))).one()
    assert tuple(user) == (7, "JC", "argon2-fixture", "active")
    assert tuple(cycle) == (11, "running", 8, 33)

    await state_engine.dispose()
    await index_engine.dispose()
