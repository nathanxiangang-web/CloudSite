"""C4 AI generate draft task handler tests.

Covers: registry registration, successful draft generation,
BudgetExceeded -> RateLimitError mapping, NoEnabledProvider -> PermanentError mapping.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import CatalogEntry
from cloudsite.platform.tasks.domain import Task
from cloudsite.platform.tasks.errors import PermanentError, RateLimitError
from cloudsite.platform.tasks.registry import get_registry
from cloudsite.plugins.ai.services import ai_completion
from cloudsite.plugins.ai.tasks.ai_generate import handle_ai_generate_draft


@pytest.fixture
async def state_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield Session
    await engine.dispose()


def _make_entry(entry_id="ce_testentry00000000000000001", **kw):
    defaults = {
        "entry_id": entry_id,
        "content_type": "software",
        "slug": "test-entry",
        "title": "Test Entry",
        "summary": "",
        "description": "",
        "status": "published",
        "revision": 1,
    }
    defaults.update(kw)
    return CatalogEntry(**defaults)


def _make_task(**payload) -> Task:
    return Task(
        task_id="tk_test00000000000000000000000001",
        task_type="ai.generate_draft",
        queue="ai",
        payload=payload,
    )


# ---- registration ----

def test_handler_registered():
    registry = get_registry()
    assert registry.has_handler("ai.generate_draft")
    assert "ai.generate_draft" in registry.get_types_for_queue("ai")


# ---- successful execution ----

async def test_handler_returns_draft_id(state_session, monkeypatch):
    import cloudsite.database as db_mod

    monkeypatch.setattr(db_mod, "StateSession", state_session)

    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()

    task = _make_task(
        target_entry_id="ce_testentry00000000000000001",
        field_type="summary",
        generated_content="Generated summary.",
        tokens_used=42,
        elapsed_ms=120,
    )
    result = await handle_ai_generate_draft(task)
    assert result["status"] == "pending"
    assert result["draft_id"].startswith("ad_")


# ---- error mapping ----

async def test_budget_exceeded_maps_to_rate_limit_error(state_session, monkeypatch):
    import cloudsite.database as db_mod

    monkeypatch.setattr(db_mod, "StateSession", state_session)

    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A",
            enabled=True, daily_budget_requests=1,
        )
        await state.commit()

    task1 = _make_task(
        target_entry_id="ce_testentry00000000000000001",
        field_type="summary",
        generated_content="c1",
    )
    await handle_ai_generate_draft(task1)  # exhausts the daily request budget

    task2 = _make_task(
        target_entry_id="ce_testentry00000000000000001",
        field_type="summary",
        generated_content="c2",
    )
    with pytest.raises(RateLimitError) as exc_info:
        await handle_ai_generate_draft(task2)
    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after >= 60


async def test_no_enabled_provider_maps_to_permanent_error(state_session, monkeypatch):
    import cloudsite.database as db_mod

    monkeypatch.setattr(db_mod, "StateSession", state_session)

    async with state_session() as state:
        state.add(_make_entry())
        await state.commit()

    task = _make_task(
        target_entry_id="ce_testentry00000000000000001",
        field_type="summary",
    )
    with pytest.raises(PermanentError):
        await handle_ai_generate_draft(task)