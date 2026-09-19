import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.modules.automation.contracts.public import (
    ParserCandidateError,
    ParserCandidateTransitionInvalid,
    cancel_parser_candidate,
    claim_parser_candidate,
    complete_parser_candidate,
    enqueue_parser_candidate,
    fail_parser_candidate,
    retry_parser_candidate,
)
from cloudsite.services.resource_name_parser import parse_resource_name


async def _state(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_enqueue_is_idempotent_and_survives_reopen(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        first, created = await enqueue_parser_candidate(
            state, resource_id="r1", input_fingerprint="abc", parser_version="1.0.0"
        )
        second, created_again = await enqueue_parser_candidate(
            state, resource_id="r1", input_fingerprint="abc", parser_version="1.0.0"
        )
        assert created is True and created_again is False
        assert first.task_id == second.task_id
        await state.commit()
        task_id = first.task_id
    async with factory() as reopened:
        assert (await reopened.get(type(first), task_id)).status == "pending"
    await engine.dispose()


async def test_complete_serializes_deterministic_evidence(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        row, _ = await enqueue_parser_candidate(
            state, resource_id="r2", input_fingerprint="def", parser_version="1.0.0"
        )
        await claim_parser_candidate(state, row.task_id)
        result = parse_resource_name("r2", "app-v1.2.3-windows-arm64.zip", extension="zip")
        completed = await complete_parser_candidate(state, row.task_id, result)
        payload = json.loads(completed.result_json)
        assert completed.status == "completed"
        assert payload["architecture"] == "arm64"
        assert payload["evidence"]["platform"]["token"] == "windows"
        with pytest.raises(ParserCandidateTransitionInvalid):
            await claim_parser_candidate(state, row.task_id)
    await engine.dispose()


async def test_failure_retry_limit_and_cancel_are_explicit(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        row, _ = await enqueue_parser_candidate(
            state, resource_id="r3", input_fingerprint="ghi", parser_version="1.0.0"
        )
        await claim_parser_candidate(state, row.task_id)
        failed = await fail_parser_candidate(state, row.task_id, "bad input")
        assert failed.status == "failed"
        pending = await retry_parser_candidate(state, row.task_id, max_retries=1)
        assert pending.status == "pending" and pending.retry_count == 1
        await cancel_parser_candidate(state, row.task_id)
        with pytest.raises(ParserCandidateTransitionInvalid):
            await retry_parser_candidate(state, row.task_id, max_retries=2)
    await engine.dispose()


async def test_result_identity_mismatch_does_not_complete(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        row, _ = await enqueue_parser_candidate(
            state, resource_id="r4", input_fingerprint="jkl", parser_version="1.0.0"
        )
        await claim_parser_candidate(state, row.task_id)
        with pytest.raises(ParserCandidateError):
            await complete_parser_candidate(
                state, row.task_id, parse_resource_name("other", "linux-x64.zip")
            )
        assert row.status == "running"
    await engine.dispose()
