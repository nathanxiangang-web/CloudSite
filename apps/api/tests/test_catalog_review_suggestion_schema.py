"""Focused persistence tests for A2 review suggestions."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version


TABLE = "catalog_review_suggestions"


def _engines(tmp_path):
    return (
        create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}"),
        create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}"),
    )


async def _init(tmp_path, monkeypatch):
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    return state_engine, index_engine


def _row(**overrides):
    values = {
        "suggestion_id": "rs_" + "a" * 32,
        "parser_candidate_task_id": "pt_" + "b" * 32,
        "resource_id": "r_" + "c" * 32,
        "suggestion_kind": "new_resource",
        "proposed_fields_json": json.dumps({"title": "Cloud Tool"}, ensure_ascii=False),
        "evidence_json": json.dumps({"source": "name-parser", "tokens": ["Cloud", "Tool"]}),
        "confidence": 0.85,
    }
    values.update(overrides)
    return models.CatalogReviewSuggestion(**values)


async def test_fresh_init_creates_v11_review_suggestion_table(tmp_path, monkeypatch):
    state_engine, index_engine = await _init(tmp_path, monkeypatch)
    async with state_engine.connect() as conn:
        assert CURRENT_SCHEMA_VERSION == 28
        assert await get_state_schema_version(conn) == 28
        columns = await conn.run_sync(
            lambda sync_conn: {item["name"] for item in inspect(sync_conn).get_columns(TABLE)}
        )
        assert columns == {
            "suggestion_id", "parser_candidate_task_id", "resource_id", "suggestion_kind",
            "proposed_entry_id", "proposed_fields_json", "evidence_json", "confidence",
            "status", "reviewed_by", "reviewed_at", "applied_entry_revision",
            "created_at", "updated_at", "error_text",
        }
        indexes = await conn.run_sync(
            lambda sync_conn: {item["name"] for item in inspect(sync_conn).get_indexes(TABLE)}
        )
        assert {
            "ix_catalog_review_suggestions_resource_id",
            "ix_catalog_review_suggestions_status",
            "ix_catalog_review_suggestions_suggestion_kind",
            "ix_catalog_review_suggestions_parser_candidate_task_id",
        } <= indexes
    await state_engine.dispose()
    await index_engine.dispose()


async def test_v10_upgrade_preserves_catalog_and_parser_rows(tmp_path, monkeypatch):
    state_engine, index_engine = await _init(tmp_path, monkeypatch)
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as state:
        state.add(models.CatalogEntry(
            entry_id="ce_upgrade", content_type="software", slug="upgrade", title="Upgrade",
        ))
        state.add(models.ParserCandidateTask(
            task_id="pt_upgrade", resource_id="r_upgrade", input_fingerprint="f" * 64,
            parser_version="1.0.0", status="completed", result_json='{"platform":"windows"}',
        ))
        await state.commit()
    async with state_engine.begin() as conn:
        await conn.exec_driver_sql(f"DROP TABLE {TABLE}")
        await conn.execute(
            text("UPDATE system_settings SET value='10' WHERE key='schema_version'")
        )

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 28
        assert (await conn.execute(text("SELECT title FROM catalog_entries WHERE entry_id='ce_upgrade'"))).scalar_one() == "Upgrade"
        assert (await conn.execute(text("SELECT status FROM parser_candidate_tasks WHERE task_id='pt_upgrade'"))).scalar_one() == "completed"
        assert TABLE in await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    await state_engine.dispose()
    await index_engine.dispose()


async def test_json_evidence_survives_reopen_without_mutating_catalog_or_user_state(tmp_path, monkeypatch):
    state_engine, index_engine = await _init(tmp_path, monkeypatch)
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as state:
        state.add(models.User(id=41, username="reviewer", username_normalized="reviewer", password_hash="hash"))
        state.add(models.CatalogEntry(
            entry_id="ce_stable", content_type="software", slug="stable", title="Stable", revision=7,
        ))
        state.add(models.UserFavorite(user_id=41, resource_id="r_stable"))
        state.add(models.CatalogSubscription(user_id=41, entry_id="ce_stable"))
        state.add(_row())
        await state.commit()
    await state_engine.dispose()
    await index_engine.dispose()

    reopened_state, reopened_index = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", reopened_state)
    monkeypatch.setattr(database, "index_engine", reopened_index)
    await database.init_databases()
    async with reopened_state.connect() as conn:
        suggestion = (await conn.execute(text(
            f"SELECT proposed_fields_json, evidence_json, status FROM {TABLE} WHERE suggestion_id=:sid"
        ), {"sid": "rs_" + "a" * 32})).one()
        assert json.loads(suggestion.proposed_fields_json) == {"title": "Cloud Tool"}
        assert json.loads(suggestion.evidence_json)["source"] == "name-parser"
        assert suggestion.status == "pending"
        assert (await conn.execute(text("SELECT title, revision FROM catalog_entries WHERE entry_id='ce_stable'"))).one() == ("Stable", 7)
        assert (await conn.execute(text("SELECT COUNT(*) FROM user_favorites"))).scalar_one() == 1
        assert (await conn.execute(text("SELECT COUNT(*) FROM catalog_subscriptions"))).scalar_one() == 1
    await reopened_state.dispose()
    await reopened_index.dispose()


async def test_duplicate_task_kind_is_rejected(tmp_path, monkeypatch):
    state_engine, index_engine = await _init(tmp_path, monkeypatch)
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as state:
        state.add(_row())
        await state.commit()
    async with factory() as state:
        state.add(_row(suggestion_id="rs_" + "d" * 32))
        with pytest.raises(IntegrityError):
            await state.commit()
    await state_engine.dispose()
    await index_engine.dispose()


@pytest.mark.parametrize(
    ("overrides"),
    [
        {"suggestion_kind": "guess"},
        {"status": "published"},
        {"confidence": -0.01},
        {"confidence": 1.01},
        {"applied_entry_revision": 0},
    ],
)
async def test_review_suggestion_constraints_fail_closed(tmp_path, monkeypatch, overrides):
    state_engine, index_engine = await _init(tmp_path, monkeypatch)
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as state:
        state.add(_row(**overrides))
        with pytest.raises(IntegrityError):
            await state.commit()
    await state_engine.dispose()
    await index_engine.dispose()


async def test_all_review_states_and_kinds_are_persistable(tmp_path, monkeypatch):
    state_engine, index_engine = await _init(tmp_path, monkeypatch)
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    kinds = ("new_resource", "new_release", "deliverable", "possible_duplicate", "conflict")
    statuses = ("pending", "reviewed", "applied", "rejected")
    async with factory() as state:
        for index, kind in enumerate(kinds):
            state.add(_row(
                suggestion_id=f"rs_kind_{index}", parser_candidate_task_id=f"pt_kind_{index}",
                suggestion_kind=kind, status=statuses[index % len(statuses)],
                applied_entry_revision=1 if statuses[index % len(statuses)] == "applied" else None,
            ))
        await state.commit()
    async with state_engine.connect() as conn:
        rows = (await conn.execute(text(f"SELECT suggestion_kind FROM {TABLE}"))).scalars().all()
        assert set(rows) == set(kinds)
    await state_engine.dispose()
    await index_engine.dispose()
