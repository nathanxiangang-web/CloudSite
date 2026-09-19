"""Focused application-layer smoke tests for the C1 Catalog service.

Covers the create / edit / bind / preview / publish flow through the
application layer only (no HTTP, no FastAPI). Scenarios:

- create: entry + exactly one default unversioned release, retry is idempotent,
  slug collision raises CatalogSlugConflict
- revision conflict: update and publish reject a stale expected_revision
- valid binding/publish: attach an in-scope indexed file then publish succeeds
- disabled-location rejection: attach rejects disabled-root resources, and
  publish rejects locations whose root was disabled after binding
- missing/inactive/content-type-mismatch rejection at attach time
- preview validation reports availability without mutating state

Full regression is deferred to integration.
"""
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import CatalogRevision, ContentRootMapping, Resource
from cloudsite.modules.catalog.contracts.public import (
    CatalogLocationInvalid,
    CatalogPublishValidationFailed,
    CatalogRevisionConflict,
    CatalogSlugConflict,
    attach_catalog_location,
    count_catalog_entries,
    create_catalog_asset,
    create_catalog_entry,
    get_catalog_entry,
    list_catalog_entries,
    publish_catalog_entry,
    update_catalog_entry,
    validate_catalog_entry_for_preview,
)
from cloudsite.modules.catalog.application.catalog_entry import DEFAULT_RELEASE_SLUG


async def _bootstrap(monkeypatch, tmp_path):
    """Three content roots + indexed resources for binding/publish tests.

    root 1 software enabled, root 2 archive disabled, root 3 document enabled.
    """
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    async with state_factory() as state:
        state.add(ContentRootMapping(id=1, content_type="software", display_name="software", alist_path="/software", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="archive", display_name="archive", alist_path="/archive", enabled=False))
        state.add(ContentRootMapping(id=3, content_type="document", display_name="document", alist_path="/document", enabled=True))
        await state.commit()

    async with index_factory() as index:
        index.add(Resource(id="r_soft_1", name="ubuntu.iso", path="/software/ubuntu.iso", parent_id=None, content_type="software", root_mapping_id=1, extension="iso", mime_type="application/x-iso", size=100, status="active"))
        index.add(Resource(id="r_arch_1", name="old.zip", path="/archive/old.zip", parent_id=None, content_type="archive", root_mapping_id=2, extension="zip", mime_type="application/zip", size=200, status="active"))
        index.add(Resource(id="r_doc_1", name="guide.pdf", path="/document/guide.pdf", parent_id=None, content_type="document", root_mapping_id=3, extension="pdf", mime_type="application/pdf", size=80, status="active"))
        index.add(Resource(id="r_soft_missing", name="gone.iso", path="/software/gone.iso", parent_id=None, content_type="software", root_mapping_id=1, extension="iso", mime_type="application/x-iso", size=50, status="missing"))
        await index.commit()

    return state_engine, index_engine, state_factory, index_factory


async def test_create_entry_and_default_release(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        result = await create_catalog_entry(
            state, content_type="software", slug="ubuntu-22-04", title="Ubuntu 22.04 LTS", summary="LTS release"
        )
        await state.commit()

        assert result.entry.status == "draft"
        assert result.entry.revision == 1
        assert result.release.entry_id == result.entry.entry_id
        assert result.release.slug == DEFAULT_RELEASE_SLUG
        assert result.release.status == "draft"

        refetched = await get_catalog_entry(state, result.entry.entry_id)
        assert refetched.entry_id == result.entry.entry_id

    await state_engine.dispose()
    await index_engine.dispose()


async def test_create_retry_is_idempotent_and_slug_conflict(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        first = await create_catalog_entry(
            state, content_type="software", slug="dup-slug", title="First",
            entry_id="ce_" + "a" * 32, release_id="cr_" + "a" * 32,
        )
        await state.commit()

        second = await create_catalog_entry(
            state, content_type="software", slug="dup-slug", title="First",
            entry_id="ce_" + "a" * 32, release_id="cr_" + "a" * 32,
        )
        assert second.entry.entry_id == first.entry.entry_id
        assert second.release.release_id == first.release.release_id

        entries = await list_catalog_entries(state, content_type="software")
        assert len(entries) == 1
        assert await count_catalog_entries(state, content_type="software") == 1
        assert await count_catalog_entries(state, status="draft") == 1
        assert await count_catalog_entries(state, status="published") == 0

        with pytest.raises(CatalogSlugConflict):
            await create_catalog_entry(
                state, content_type="software", slug="dup-slug", title="Different",
                entry_id="ce_" + "b" * 32,
            )

        entries = await list_catalog_entries(state, content_type="software")
        assert len(entries) == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_update_revision_conflict_and_increment(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        result = await create_catalog_entry(state, content_type="software", slug="rev-check", title="Rev")
        await state.commit()

        with pytest.raises(CatalogRevisionConflict) as exc:
            await update_catalog_entry(state, result.entry.entry_id, expected_revision=999, title="Stale")
        assert exc.value.expected == 999
        assert exc.value.actual == 1

        updated = await update_catalog_entry(
            state, result.entry.entry_id, expected_revision=1, title="Rev v2", summary="updated"
        )
        await state.commit()
        assert updated.revision == 2
        assert updated.title == "Rev v2"

        revisions = list(
            (
                await state.scalars(
                    select(CatalogRevision).where(
                        CatalogRevision.target_id == result.entry.entry_id
                    )
                )
            ).all()
        )
        assert [row.action for row in revisions] == ["create", "update"]
        assert revisions[-1].base_revision == 1
        assert revisions[-1].resulting_revision == 2

        with pytest.raises(CatalogRevisionConflict):
            await update_catalog_entry(state, result.entry.entry_id, expected_revision=1, title="Stale again")

    await state_engine.dispose()
    await index_engine.dispose()


async def test_attach_and_publish_valid_location(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(state, content_type="software", slug="bind-publish", title="Bind")
        asset_result = await create_catalog_asset(
            state, release_id=entry_result.release.release_id, slug="amd64-iso", display_name="ubuntu-amd64.iso"
        )
        attach = await attach_catalog_location(
            state, index, asset_id=asset_result.asset.asset_id, resource_id="r_soft_1", label="cn-mirror", is_primary=True
        )
        await state.commit()

        assert attach.resolution.available is True
        assert attach.location.resource_id == "r_soft_1"
        assert attach.location.root_mapping_id == 1
        assert attach.location.is_primary is True

        preview = await validate_catalog_entry_for_preview(state, index, entry_result.entry.entry_id)
        assert preview.status == "draft"
        assert preview.available is False

        published = await publish_catalog_entry(
            state, index, entry_result.entry.entry_id, expected_revision=entry_result.entry.revision
        )
        await state.commit()

        assert published.entry.status == "published"
        assert published.entry.published_at is not None
        assert published.entry.revision == 2

        preview_after = await validate_catalog_entry_for_preview(state, index, entry_result.entry.entry_id)
        assert preview_after.available is True
        assert preview_after.unavailable_locations == []

    await state_engine.dispose()
    await index_engine.dispose()


async def test_attach_rejects_disabled_root(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(state, content_type="archive", slug="disabled-attach", title="Disabled")
        asset_result = await create_catalog_asset(
            state, release_id=entry_result.release.release_id, slug="zip", display_name="old.zip"
        )
        with pytest.raises(CatalogLocationInvalid) as exc:
            await attach_catalog_location(
                state, index, asset_id=asset_result.asset.asset_id, resource_id="r_arch_1"
            )
        assert exc.value.reason == "disabled_root"
        await state.rollback()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_attach_rejects_missing_inactive_mismatch(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(state, content_type="software", slug="reject", title="Reject")
        asset_result = await create_catalog_asset(
            state, release_id=entry_result.release.release_id, slug="asset", display_name="asset"
        )

        with pytest.raises(CatalogLocationInvalid) as exc:
            await attach_catalog_location(
                state, index, asset_id=asset_result.asset.asset_id, resource_id="r_does_not_exist"
            )
        assert exc.value.reason == "missing"

        with pytest.raises(CatalogLocationInvalid) as exc:
            await attach_catalog_location(
                state, index, asset_id=asset_result.asset.asset_id, resource_id="r_soft_missing"
            )
        assert exc.value.reason == "inactive"

        with pytest.raises(CatalogLocationInvalid) as exc:
            await attach_catalog_location(
                state, index, asset_id=asset_result.asset.asset_id, resource_id="r_doc_1"
            )
        assert exc.value.reason == "content_type_mismatch"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_location_disabled_after_binding(tmp_path, monkeypatch):
    """A location valid at bind time must fail publish after its root is disabled."""
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(state, content_type="software", slug="disable-after", title="DisableAfter")
        asset_result = await create_catalog_asset(
            state, release_id=entry_result.release.release_id, slug="iso", display_name="ubuntu.iso"
        )
        await attach_catalog_location(state, index, asset_id=asset_result.asset.asset_id, resource_id="r_soft_1")
        await state.commit()

    async with sf() as state, ix() as index:
        await state.execute(update(ContentRootMapping).where(ContentRootMapping.id == 1).values(enabled=False))
        await state.commit()

    async with sf() as state, ix() as index:
        with pytest.raises(CatalogPublishValidationFailed) as exc:
            await publish_catalog_entry(
                state, index, entry_result.entry.entry_id, expected_revision=entry_result.entry.revision
            )
        assert exc.value.entry_id == entry_result.entry.entry_id
        assert any("disabled_root" in r for r in exc.value.reasons)

        still_draft = await get_catalog_entry(state, entry_result.entry.entry_id)
        assert still_draft.status == "draft"
        assert still_draft.revision == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_revision_conflict(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(state, content_type="software", slug="pub-conflict", title="PubConflict")
        await state.commit()

        with pytest.raises(CatalogRevisionConflict):
            await publish_catalog_entry(state, index, entry_result.entry.entry_id, expected_revision=4242)

    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_entry_without_available_location(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(
            state, content_type="software", slug="no-location", title="NoLocation"
        )
        await state.commit()

        with pytest.raises(CatalogPublishValidationFailed) as exc:
            await publish_catalog_entry(
                state,
                index,
                entry_result.entry.entry_id,
                expected_revision=entry_result.entry.revision,
            )
        assert any("no available active" in reason for reason in exc.value.reasons)
        assert entry_result.entry.status == "draft"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rechecks_content_type_after_entry_update(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(
            state, content_type="software", slug="changed-type", title="ChangedType"
        )
        asset_result = await create_catalog_asset(
            state,
            release_id=entry_result.release.release_id,
            slug="iso",
            display_name="ubuntu.iso",
        )
        await attach_catalog_location(
            state,
            index,
            asset_id=asset_result.asset.asset_id,
            resource_id="r_soft_1",
        )
        await update_catalog_entry(
            state,
            entry_result.entry.entry_id,
            expected_revision=entry_result.entry.revision,
            content_type="document",
        )
        await state.commit()

        with pytest.raises(CatalogPublishValidationFailed) as exc:
            await publish_catalog_entry(
                state,
                index,
                entry_result.entry.entry_id,
                expected_revision=entry_result.entry.revision,
            )
        assert any("content_type_mismatch" in reason for reason in exc.value.reasons)

    await state_engine.dispose()
    await index_engine.dispose()


async def test_preview_does_not_mutate_state(tmp_path, monkeypatch):
    state_engine, index_engine, sf, ix = await _bootstrap(monkeypatch, tmp_path)
    async with sf() as state, ix() as index:
        entry_result = await create_catalog_entry(state, content_type="software", slug="preview", title="Preview")
        asset_result = await create_catalog_asset(
            state, release_id=entry_result.release.release_id, slug="iso", display_name="ubuntu.iso"
        )
        await attach_catalog_location(state, index, asset_id=asset_result.asset.asset_id, resource_id="r_soft_1")
        await state.commit()

        preview = await validate_catalog_entry_for_preview(state, index, entry_result.entry.entry_id)
        assert preview.available is False
        assert preview.status == "draft"
        assert len(preview.releases) == 1
        assert preview.releases[0]["assets"][0]["available"] is True

        entry = await get_catalog_entry(state, entry_result.entry.entry_id)
        assert entry.status == "draft"
        assert entry.revision == 1

    await state_engine.dispose()
    await index_engine.dispose()
