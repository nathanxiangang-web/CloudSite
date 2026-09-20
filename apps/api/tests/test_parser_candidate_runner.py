from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Resource
from cloudsite.modules.automation.contracts.public import (
    parser_input_fingerprint,
    run_parser_candidate,
)
from cloudsite.modules.automation.contracts.public import enqueue_parser_candidate
from cloudsite.modules.automation.domain.resource_name_parser import PARSER_VERSION


async def _sessions(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    return (
        state_engine,
        index_engine,
        async_sessionmaker(state_engine, expire_on_commit=False),
        async_sessionmaker(index_engine, expire_on_commit=False),
    )


def _resource(resource_id: str = "r_runner") -> Resource:
    return Resource(
        id=resource_id,
        name="Tool-2.4.1-Windows-arm64.zip",
        path="/software/Tool-2.4.1-Windows-arm64.zip",
        content_type="software",
        extension="zip",
        mime_type="application/zip",
        status="active",
    )


async def test_runner_completes_exact_fingerprint(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        resource = _resource()
        index.add(resource)
        await index.flush()
        task, _ = await enqueue_parser_candidate(
            state,
            resource_id=resource.id,
            input_fingerprint=parser_input_fingerprint(resource),
            parser_version=PARSER_VERSION,
        )

        outcome = await run_parser_candidate(state, index, task.task_id)

        assert outcome.error is None
        assert outcome.task.status == "completed"
        assert outcome.result is not None
        assert outcome.result.platform == "windows"
        assert outcome.result.architecture == "arm64"
        assert outcome.result.version == "2.4.1"
        assert outcome.result.package_form == "zip"
        assert outcome.task.result_json is not None
    await state_engine.dispose()
    await index_engine.dispose()


async def test_runner_fails_closed_for_stale_fingerprint(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        resource = _resource()
        index.add(resource)
        await index.flush()
        task, _ = await enqueue_parser_candidate(
            state,
            resource_id=resource.id,
            input_fingerprint="0" * 64,
            parser_version=PARSER_VERSION,
        )

        outcome = await run_parser_candidate(state, index, task.task_id)

        assert outcome.task.status == "failed"
        assert outcome.result is None
        assert outcome.error == "parser input fingerprint is stale"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_runner_fails_closed_for_missing_resource_or_parser_version(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        missing, _ = await enqueue_parser_candidate(
            state,
            resource_id="r_missing",
            input_fingerprint="1" * 64,
            parser_version=PARSER_VERSION,
        )
        missing_outcome = await run_parser_candidate(state, index, missing.task_id)
        assert missing_outcome.task.status == "failed"
        assert missing_outcome.error == "parser input resource is unavailable"

        unsupported, _ = await enqueue_parser_candidate(
            state,
            resource_id="r_other",
            input_fingerprint="2" * 64,
            parser_version="999.0",
        )
        unsupported_outcome = await run_parser_candidate(state, index, unsupported.task_id)
        assert unsupported_outcome.task.status == "failed"
        assert unsupported_outcome.error == "unsupported parser version: 999.0"
    await state_engine.dispose()
    await index_engine.dispose()
