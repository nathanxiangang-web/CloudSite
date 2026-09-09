"""Focused C3 metadata service checks."""
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import CatalogEntry, CatalogRevision, CatalogTag
from cloudsite.services.catalog_metadata import (
    CatalogMetadataConflict,
    CatalogMetadataInvalid,
    CatalogMetadataNotFound,
    assign_catalog_tag,
    create_catalog_relation,
    create_catalog_tag,
    delete_catalog_relation,
    delete_catalog_tag,
    list_catalog_relations,
    list_catalog_revisions,
    remove_catalog_tag_assignment,
    update_catalog_tag,
)


async def _state(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _entry(entry_id: str, slug: str, status: str = "draft") -> CatalogEntry:
    return CatalogEntry(
        entry_id=entry_id,
        content_type="software",
        slug=slug,
        title=slug,
        status=status,
    )


async def test_tag_assignment_is_validated_idempotent_and_audited(tmp_path):
    engine, factory = await _state(tmp_path)
    entry_id = "ce_" + "1" * 32
    async with factory() as state:
        state.add(_entry(entry_id, "first"))
        tag = await create_catalog_tag(
            state, slug="long-term", display_name="Long Term", actor="admin"
        )
        first = await assign_catalog_tag(
            state,
            tag_id=tag.tag_id,
            target_type="entry",
            target_id=entry_id,
            actor="admin",
        )
        second = await assign_catalog_tag(
            state,
            tag_id=tag.tag_id,
            target_type="entry",
            target_id=entry_id,
            actor="admin",
        )
        await state.commit()
        assert first.tag_id == second.tag_id
        revisions = list((await state.scalars(select(CatalogRevision))).all())
        assert [row.action for row in revisions] == ["create", "update"]
        assert json.loads(revisions[1].payload_json) == {"tag_id": tag.tag_id}

        assert await remove_catalog_tag_assignment(
            state,
            tag_id=tag.tag_id,
            target_type="entry",
            target_id=entry_id,
            actor="admin",
        )
        assert not await remove_catalog_tag_assignment(
            state,
            tag_id=tag.tag_id,
            target_type="entry",
            target_id=entry_id,
            actor="admin",
        )
        await state.commit()

    await engine.dispose()


async def test_tag_rejects_bad_slug_and_missing_target(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        with pytest.raises(CatalogMetadataInvalid):
            await create_catalog_tag(state, slug="Not Safe", display_name="Bad")
        tag = await create_catalog_tag(state, slug="safe", display_name="Safe")
        with pytest.raises(CatalogMetadataNotFound):
            await assign_catalog_tag(
                state,
                tag_id=tag.tag_id,
                target_type="entry",
                target_id="ce_" + "9" * 32,
            )
        with pytest.raises(CatalogMetadataInvalid):
            await assign_catalog_tag(
                state, tag_id=tag.tag_id, target_type="unknown", target_id="x"
            )
    await engine.dispose()


async def test_tag_slug_conflict_is_deterministic(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        await create_catalog_tag(state, slug="stable", display_name="Stable")
        with pytest.raises(CatalogMetadataConflict):
            await create_catalog_tag(state, slug="stable", display_name="Duplicate")
    await engine.dispose()


async def test_public_relations_hide_unpublished_targets(tmp_path):
    engine, factory = await _state(tmp_path)
    first_id = "ce_" + "2" * 32
    second_id = "ce_" + "3" * 32
    async with factory() as state:
        state.add_all(
            [
                _entry(first_id, "published-source", "published"),
                _entry(second_id, "draft-target", "draft"),
            ]
        )
        relation = await create_catalog_relation(
            state,
            from_entry_id=first_id,
            to_entry_id=second_id,
            relation_type="companion",
            actor="editor",
        )
        assert len(await list_catalog_relations(state, from_entry_id=first_id)) == 1
        assert await list_catalog_relations(
            state, from_entry_id=first_id, published_only=True
        ) == []

        target = await state.get(CatalogEntry, second_id)
        assert target is not None
        target.status = "published"
        await state.flush()
        visible = await list_catalog_relations(
            state, from_entry_id=first_id, published_only=True
        )
        assert [row.relation_id for row in visible] == [relation.relation_id]

        await delete_catalog_relation(state, relation.relation_id, actor="editor")
        await state.commit()
        revisions = list((await state.scalars(select(CatalogRevision))).all())
        assert [row.action for row in revisions] == ["create", "delete"]

    await engine.dispose()


async def test_relation_rejects_self_missing_and_duplicate(tmp_path):
    engine, factory = await _state(tmp_path)
    first_id = "ce_" + "4" * 32
    second_id = "ce_" + "5" * 32
    async with factory() as state:
        state.add_all([_entry(first_id, "one"), _entry(second_id, "two")])
        await state.flush()
        with pytest.raises(CatalogMetadataInvalid):
            await create_catalog_relation(
                state,
                from_entry_id=first_id,
                to_entry_id=first_id,
                relation_type="variant",
            )
        with pytest.raises(CatalogMetadataNotFound):
            await create_catalog_relation(
                state,
                from_entry_id=first_id,
                to_entry_id="ce_" + "6" * 32,
                relation_type="companion",
            )
        await create_catalog_relation(
            state,
            from_entry_id=first_id,
            to_entry_id=second_id,
            relation_type="companion",
        )
        with pytest.raises(CatalogMetadataConflict):
            await create_catalog_relation(
                state,
                from_entry_id=first_id,
                to_entry_id=second_id,
                relation_type="companion",
            )
    await engine.dispose()



async def test_tag_update_changes_fields_and_appends_audit(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        tag = await create_catalog_tag(state, slug="original", display_name="Original")
        updated = await update_catalog_tag(
            state, tag_id=tag.tag_id, slug="renamed", display_name="Renamed", actor="admin"
        )
        assert updated.slug == "renamed"
        assert updated.display_name == "Renamed"
        await state.commit()
        revisions = list((await state.scalars(select(CatalogRevision))).all())
        assert [row.action for row in revisions] == ["create", "update"]
        assert json.loads(revisions[1].before_json) == {"slug": "original", "display_name": "Original"}
        assert json.loads(revisions[1].after_json) == {"slug": "renamed", "display_name": "Renamed"}
    await engine.dispose()


async def test_tag_update_rejects_duplicate_slug_and_missing_tag(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        await create_catalog_tag(state, slug="first", display_name="First")
        second = await create_catalog_tag(state, slug="second", display_name="Second")
        with pytest.raises(CatalogMetadataConflict):
            await update_catalog_tag(state, tag_id=second.tag_id, slug="first")
        with pytest.raises(CatalogMetadataNotFound):
            await update_catalog_tag(state, tag_id="ct_" + "0" * 32, slug="x")
    await engine.dispose()


async def test_tag_delete_removes_tag_and_appends_audit(tmp_path):
    engine, factory = await _state(tmp_path)
    entry_id = "ce_" + "7" * 32
    async with factory() as state:
        state.add(_entry(entry_id, "tagged"))
        tag = await create_catalog_tag(state, slug="removable", display_name="Removable")
        await assign_catalog_tag(
            state, tag_id=tag.tag_id, target_type="entry", target_id=entry_id
        )
        await delete_catalog_tag(state, tag.tag_id, actor="admin")
        await state.commit()
        assert await state.get(CatalogTag, tag.tag_id) is None
        revisions = list((await state.scalars(select(CatalogRevision))).all())
        assert [row.action for row in revisions] == ["create", "update", "delete"]
        assert revisions[2].target_type == "tag"
    await engine.dispose()


async def test_list_catalog_revisions_filters_and_paginates(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        tag = await create_catalog_tag(state, slug="alpha", display_name="Alpha", actor="admin")
        await update_catalog_tag(state, tag_id=tag.tag_id, display_name="Beta", actor="editor")
        await state.commit()
        all_rows, total = await list_catalog_revisions(state)
        assert total == 2
        assert [row.action for row in all_rows] == ["create", "update"]
        filtered, total = await list_catalog_revisions(state, action="update")
        assert total == 1
        assert filtered[0].action == "update"
        by_actor, total = await list_catalog_revisions(state, actor="editor")
        assert total == 1
        assert by_actor[0].actor == "editor"
        page, total = await list_catalog_revisions(state, limit=1, offset=0)
        assert len(page) == 1
        assert page[0].action == "create"
        page2, total = await list_catalog_revisions(state, limit=1, offset=1)
        assert len(page2) == 1
        assert page2[0].action == "update"
        by_target, total = await list_catalog_revisions(state, target_type="tag", target_id=tag.tag_id)
        assert total == 2
    await engine.dispose()


async def test_list_catalog_revisions_rejects_bad_filters(tmp_path):
    engine, factory = await _state(tmp_path)
    async with factory() as state:
        with pytest.raises(CatalogMetadataInvalid):
            await list_catalog_revisions(state, target_type="bogus")
        with pytest.raises(CatalogMetadataInvalid):
            await list_catalog_revisions(state, action="bogus")
    await engine.dispose()
