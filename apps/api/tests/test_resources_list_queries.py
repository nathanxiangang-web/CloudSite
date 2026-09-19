"""Resources list-query boundary tests."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.resources.domain.views import ResourceSummaryView
from cloudsite.modules.resources.infrastructure.models import Folder, Resource
from cloudsite.modules.resources.infrastructure.query_repository import (
    SqlAlchemyResourceQueryRepository,
)
from cloudsite.platform.db import IndexBase


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    return engine, factory


async def _seed(factory):
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    async with factory() as session:
        session.add_all(
            [
                Folder(
                    id="f_root_1",
                    name="root-one",
                    path="/one",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    depth=0,
                    status="active",
                    indexed_at=now,
                ),
                Folder(
                    id="f_child_1",
                    name="child-one",
                    path="/one/child",
                    parent_id="f_root_1",
                    content_type="software",
                    root_mapping_id=1,
                    depth=1,
                    status="active",
                    indexed_at=now,
                ),
                Folder(
                    id="f_root_2",
                    name="root-two",
                    path="/two",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=2,
                    depth=0,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r_a",
                    name="a.zip",
                    path="/one/a.zip",
                    parent_id="f_root_1",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=10,
                    modified_at=now,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r_b",
                    name="b.zip",
                    path="/one/b.zip",
                    parent_id="f_root_1",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=20,
                    modified_at=now,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r_hidden",
                    name="hidden.zip",
                    path="/two/hidden.zip",
                    parent_id="f_root_2",
                    content_type="software",
                    root_mapping_id=2,
                    extension="zip",
                    mime_type="application/zip",
                    size=99,
                    modified_at=now,
                    status="active",
                    indexed_at=now,
                ),
            ]
        )
        await session.commit()


async def test_list_resources_preserves_scope_sort_parent_and_pagination():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        page = await repository.list_resources(
            enabled_root_ids={1},
            content_type="software",
            parent_id="f_root_1",
            page=1,
            page_size=1,
            sort="size",
            order="desc",
        )

        assert page.total == 2
        assert page.total_pages == 2
        assert len(page.items) == 1
        assert page.items[0].id == "r_b"
        assert page.items[0].parent is not None
        assert page.items[0].parent.id == "f_root_1"

    await engine.dispose()


async def test_list_resources_empty_scope_matches_legacy_publication_behavior():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        page = await repository.list_resources(
            enabled_root_ids=set(),
            content_type=None,
            parent_id=None,
            page=1,
            page_size=24,
            sort="modified_at",
            order="desc",
        )
        assert page.total == 0
        assert page.items == ()

    await engine.dispose()


async def test_list_folders_preserves_parent_filter_semantics():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)

        all_visible = await repository.list_folders(
            enabled_root_ids={1},
            content_type="software",
            parent_id=None,
            parent_filter_supplied=False,
        )
        assert [item.id for item in all_visible] == ["f_root_1", "f_child_1"]

        roots_only = await repository.list_folders(
            enabled_root_ids={1},
            content_type="software",
            parent_id=None,
            parent_filter_supplied=True,
        )
        assert [item.id for item in roots_only] == ["f_root_1"]

        children = await repository.list_folders(
            enabled_root_ids={1},
            content_type="software",
            parent_id="f_root_1",
            parent_filter_supplied=True,
        )
        assert [item.id for item in children] == ["f_child_1"]

    await engine.dispose()


def test_resource_summary_omits_parent_key_when_parent_is_absent():
    view = ResourceSummaryView(
        id="r_root",
        name="root.txt",
        parent_id=None,
        content_type="document",
        extension="txt",
        mime_type="text/plain",
        size=1,
        modified_at=None,
    )
    payload = view.to_dict()
    assert "parent" not in payload
