"""Regression tests for the Automation parser ownership boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.models import ParserCandidateTask as LegacyParserCandidateTask
from cloudsite.modules.automation.domain.resource_name_parser import (
    Evidence,
    ParseResult,
    parse_resource_name,
)
from cloudsite.modules.automation.infrastructure.models import ParserCandidateTask
from cloudsite.modules.resources.contracts.public import ParserResourceView, resource_queries
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.platform.db import IndexBase, StateBase
from cloudsite.services.resource_name_parser import (
    Evidence as LegacyEvidence,
    ParseResult as LegacyParseResult,
    parse_resource_name as legacy_parse_resource_name,
)


def test_legacy_parser_candidate_export_is_exact_module_class():
    assert LegacyParserCandidateTask is ParserCandidateTask
    assert ParserCandidateTask.__module__ == (
        "cloudsite.modules.automation.infrastructure.models"
    )
    assert ParserCandidateTask.__tablename__ == "parser_candidate_tasks"
    assert "parser_candidate_tasks" in StateBase.metadata.tables


def test_legacy_parser_facade_reexports_module_domain_objects():
    assert LegacyEvidence is Evidence
    assert LegacyParseResult is ParseResult
    assert legacy_parse_resource_name is parse_resource_name


async def test_resources_contract_returns_parser_safe_projection():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with factory() as session:
        session.add(
            Resource(
                id="r_parser_boundary",
                name="Tool-2.1.0-linux-x64.zip",
                path="/software/Tool-2.1.0-linux-x64.zip",
                parent_id=None,
                content_type="software",
                root_mapping_id=7,
                extension="zip",
                mime_type="application/zip",
                size=42,
                status="active",
            )
        )
        await session.commit()

    async with factory() as session:
        view = await resource_queries(session).parser_resource(
            resource_id="r_parser_boundary"
        )
        assert isinstance(view, ParserResourceView)
        assert view.id == "r_parser_boundary"
        assert view.name == "Tool-2.1.0-linux-x64.zip"
        assert view.path == "/software/Tool-2.1.0-linux-x64.zip"
        assert view.extension == "zip"
        assert view.mime_type == "application/zip"
        assert view.status == "active"
        assert view.content_type == "software"
        assert view.size == 42
        assert view.indexed_at is not None
        assert not hasattr(view, "root_mapping_id")

        listed = await resource_queries(session).list_parser_resources(
            content_type="software",
            limit=10,
        )
        assert [item.id for item in listed] == ["r_parser_boundary"]
        assert listed[0].size == 42
        assert listed[0].content_type == "software"

        assert (
            await resource_queries(session).parser_resource(resource_id="missing")
            is None
        )

    await engine.dispose()
