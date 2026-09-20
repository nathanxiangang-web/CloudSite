"""A3 AI completion service tests.

 Covers: config CRUD, draft generation with dedup, budget control,
 accept/reject/modify state transitions, accept writes to catalog entry,
 no enabled provider error, disabled provider rejection.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import AIBudgetUsage, AIGenerationDraft, AIProviderConfig, CatalogEntry
from cloudsite.plugins.ai.services import ai_completion


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


# ---- config management ----

async def test_create_and_get_config(state_session):
    async with state_session() as state:
        summary = await ai_completion.create_provider_config(
            state,
            provider_type="local_ollama",
            display_name="Local Ollama",
            endpoint_url="http://localhost:11434",
            model_name="llama3",
            enabled=True,
        )
        await state.commit()
        assert summary.config_id.startswith("ac_")
        assert summary.enabled is True

    async with state_session() as state:
        fetched = await ai_completion.get_provider_config(state, summary.config_id)
        assert fetched.display_name == "Local Ollama"


async def test_list_configs(state_session):
    async with state_session() as state:
        await ai_completion.create_provider_config(state, provider_type="local_ollama", display_name="A", enabled=True)
        await ai_completion.create_provider_config(state, provider_type="openai_compatible", display_name="B", enabled=False)
        await state.commit()
    async with state_session() as state:
        all_configs = await ai_completion.list_provider_configs(state)
        assert len(all_configs) == 2
        enabled = await ai_completion.list_provider_configs(state, enabled_only=True)
        assert len(enabled) == 1


async def test_update_config(state_session):
    async with state_session() as state:
        summary = await ai_completion.create_provider_config(state, provider_type="local_ollama", display_name="A")
        await state.commit()
    async with state_session() as state:
        updated = await ai_completion.update_provider_config(state, summary.config_id, enabled=True, display_name="Updated")
        await state.commit()
        assert updated.enabled is True
        assert updated.display_name == "Updated"


async def test_delete_config(state_session):
    async with state_session() as state:
        summary = await ai_completion.create_provider_config(state, provider_type="local_ollama", display_name="A")
        await state.commit()
    async with state_session() as state:
        await ai_completion.delete_provider_config(state, summary.config_id)
        await state.commit()
    async with state_session() as state:
        with pytest.raises(ai_completion.ProviderConfigNotFound):
            await ai_completion.get_provider_config(state, summary.config_id)


async def test_config_not_found(state_session):
    async with state_session() as state:
        with pytest.raises(ai_completion.ProviderConfigNotFound):
            await ai_completion.get_provider_config(state, "ac_nonexistent00000000000000000000")


# ---- generation ----

async def test_generate_draft_with_enabled_provider(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        result = await ai_completion.generate_draft(
            state,
            target_entry_id="ce_testentry00000000000000001",
            field_type="summary",
            generated_content="This is a test entry for software.",
            tokens_used=50,
        )
        await state.commit()
        assert result.draft_id.startswith("ad_")
        assert result.status == "pending"


async def test_generate_draft_no_enabled_provider(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await state.commit()
    async with state_session() as state:
        with pytest.raises(ai_completion.NoEnabledProvider):
            await ai_completion.generate_draft(
                state,
                target_entry_id="ce_testentry00000000000000001",
                field_type="summary",
            )


async def test_generate_draft_disabled_provider_rejected(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        config = await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=False,
        )
        await state.commit()
    async with state_session() as state:
        with pytest.raises(ai_completion.DraftStateInvalid):
            await ai_completion.generate_draft(
                state,
                target_entry_id="ce_testentry00000000000000001",
                field_type="summary",
                config_id=config.config_id,
            )


async def test_generate_draft_dedup(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        r1 = await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="content1",
        )
        await state.commit()
    async with state_session() as state:
        r2 = await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="content2",
        )
        await state.commit()
        assert r1.draft_id == r2.draft_id
        assert r2.generated_content == "content1"


# ---- budget control ----

async def test_budget_tracking(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        config = await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A",
            enabled=True, daily_budget_requests=5, daily_budget_tokens=1000,
        )
        await state.commit()
    for field_type in ("summary", "tags", "aliases"):
        async with state_session() as state:
            await ai_completion.generate_draft(
                state, target_entry_id="ce_testentry00000000000000001",
                field_type=field_type, generated_content=f"c_{field_type}",
                tokens_used=100,
            )
            await state.commit()
    async with state_session() as state:
        usage = await ai_completion.get_budget_usage(state, config.config_id)
        assert usage["requests_used"] == 3
        assert usage["tokens_used"] == 300


async def test_budget_exceeded_requests(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A",
            enabled=True, daily_budget_requests=1,
        )
        await state.commit()
    async with state_session() as state:
        await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="c1",
        )
        await state.commit()
    async with state_session() as state:
        with pytest.raises(ai_completion.BudgetExceeded):
            await ai_completion.generate_draft(
                state, target_entry_id="ce_testentry00000000000000001",
                field_type="summary", generated_content="c2",
            )


async def test_budget_exceeded_tokens(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A",
            enabled=True, daily_budget_tokens=50,
        )
        await state.commit()
    async with state_session() as state:
        await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="c1", tokens_used=60,
        )
        await state.commit()
    async with state_session() as state:
        with pytest.raises(ai_completion.BudgetExceeded):
            await ai_completion.generate_draft(
                state, target_entry_id="ce_testentry00000000000000001",
                field_type="tags", generated_content="c2",
            )


# ---- draft review ----

async def test_accept_draft_writes_summary(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        result = await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="AI generated summary",
        )
        await state.commit()
        draft_id = result.draft_id

    async with state_session() as state:
        summary = await ai_completion.accept_draft(state, draft_id)
        await state.commit()
        assert summary.candidate_status == "accepted"

    async with state_session() as state:
        entry = await state.scalar(select(CatalogEntry).where(CatalogEntry.entry_id == "ce_testentry00000000000000001"))
        assert entry.summary == "AI generated summary"


async def test_reject_draft(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        result = await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="bad content",
        )
        await state.commit()
    async with state_session() as state:
        summary = await ai_completion.reject_draft(state, result.draft_id, reason="inaccurate")
        await state.commit()
        assert summary.candidate_status == "rejected"
        assert summary.error_message == "inaccurate"


async def test_modify_draft_writes_modified_content(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        result = await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="original",
        )
        await state.commit()
    async with state_session() as state:
        summary = await ai_completion.modify_draft(state, result.draft_id, modified_content="corrected by admin")
        await state.commit()
        assert summary.candidate_status == "modified"
        assert summary.generated_content == "corrected by admin"

    async with state_session() as state:
        entry = await state.scalar(select(CatalogEntry).where(CatalogEntry.entry_id == "ce_testentry00000000000000001"))
        assert entry.summary == "corrected by admin"


async def test_accept_already_accepted_fails(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        result = await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="content",
        )
        await state.commit()
    async with state_session() as state:
        await ai_completion.accept_draft(state, result.draft_id)
        await state.commit()
    async with state_session() as state:
        with pytest.raises(ai_completion.DraftStateInvalid):
            await ai_completion.accept_draft(state, result.draft_id)


# ---- list/get ----

async def test_list_drafts(state_session):
    async with state_session() as state:
        state.add(_make_entry())
        await ai_completion.create_provider_config(
            state, provider_type="local_ollama", display_name="A", enabled=True,
        )
        await state.commit()
    async with state_session() as state:
        await ai_completion.generate_draft(
            state, target_entry_id="ce_testentry00000000000000001",
            field_type="summary", generated_content="s",
        )
        await state.commit()
    async with state_session() as state:
        items, total = await ai_completion.list_drafts(state, target_id="ce_testentry00000000000000001")
        assert total == 1
        assert items[0].field_type == "summary"
    async with state_session() as state:
        items, total = await ai_completion.list_drafts(state, candidate_status="accepted")
        assert total == 0


async def test_get_draft_not_found(state_session):
    async with state_session() as state:
        with pytest.raises(ai_completion.DraftNotFound):
            await ai_completion.get_draft(state, "ad_nonexistent00000000000000000000")