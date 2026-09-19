"""Resources detail-query repository regression tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.resources.domain.errors import (
    FolderNotFoundError,
    ResourceNotAvailableError,
    ResourceNotFoundError,
)
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
                    id="f_root",
                    name="Root",
                    path="/root",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    depth=0,
                    status="active",
                    indexed_at=now,
                ),
                Folder(
                    id="f_child",
                    name="Child",
                    path="/root/child",
                    parent_id="f_root",
                    content_type="software",
                    root_mapping_id=1,
                    depth=1,
                    status="active",
                    indexed_at=now,
                ),
                Folder(
                    id="f_sub",
                    name="Sub",
                    path="/root/child/sub",
                    parent_id="f_child",
                    content_type="software",
                    root_mapping_id=1,
                    depth=2,
                    status="active",
                    indexed_at=now,
                ),
            ]
        )
        for rid, name, size, root, status in [
            ("r_a", "alpha.zip", 10, 1, "active"),
            ("r_b", "bravo.zip", 20, 1, "active"),
            ("r_c", "charlie.zip", 30, 1, "active"),
            ("r_other", "other.zip", 40, 2, "active"),
            ("r_inactive", "inactive.zip", 50, 1, "missing"),
        ]:
            session.add(
                Resource(
                    id=rid,
                    name=name,
                    path=f"/root/child/{name}",
                    parent_id="f_child",
                    content_type="software",
                    root_mapping_id=root,
                    extension="zip",
                    mime_type="application/zip",
                    size=size,
                    modified_at=now,
                    status=status,
                    indexed_at=now,
                )
            )
        await session.commit()


async def test_resource_detail_preserves_breadcrumb_and_sibling_scope():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        detail = await repository.resource_detail(
            resource_id="r_b",
            enabled_root_ids={1, 2},
        )

        assert [item.id for item in detail.breadcrumbs] == ["f_root", "f_child"]
        assert {item.id for item in detail.related} == {"r_a", "r_c"}
        assert detail.previous is not None
        assert detail.previous.id == "r_a"
        assert detail.next is not None
        assert detail.next.id == "r_c"
        assert all(item.id != "r_other" for item in detail.related)

    await engine.dispose()


async def test_resource_detail_distinguishes_missing_from_out_of_scope():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)

        with pytest.raises(ResourceNotFoundError):
            await repository.resource_detail(
                resource_id="r_missing",
                enabled_root_ids={1},
            )
        with pytest.raises(ResourceNotFoundError):
            await repository.resource_detail(
                resource_id="r_inactive",
                enabled_root_ids={1},
            )
        with pytest.raises(ResourceNotAvailableError):
            await repository.resource_detail(
                resource_id="r_other",
                enabled_root_ids={1},
            )

    await engine.dispose()


async def test_folder_detail_preserves_breadcrumb_children_sort_and_pagination():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        detail = await repository.folder_detail(
            folder_id="f_child",
            enabled_root_ids={1},
            page=1,
            page_size=1,
            sort="size",
            order="desc",
        )

        assert detail.folder.id == "f_child"
        assert [item.id for item in detail.breadcrumbs] == ["f_root", "f_child"]
        assert [item.id for item in detail.child_folders] == ["f_sub"]
        assert detail.resources.total == 3
        assert detail.resources.total_pages == 3
        assert [item.id for item in detail.resources.items] == ["r_c"]

    await engine.dispose()


async def test_folder_detail_rejects_disabled_scope():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        with pytest.raises(FolderNotFoundError):
            await repository.folder_detail(
                folder_id="f_child",
                enabled_root_ids={2},
                page=1,
                page_size=24,
                sort="name",
                order="asc",
            )

    await engine.dispose()
