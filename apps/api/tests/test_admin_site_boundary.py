"""Regression coverage for admin Site persistence helpers."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import SiteSettings
from cloudsite.site import (
    clear_share_page_image_name,
    get_admin_site_settings,
    replace_share_page_image_name,
    update_admin_site_settings,
)


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_admin_site_settings_persist_behind_service_boundary():
    engine, factory = await _store()
    async with factory() as state:
        payload = await get_admin_site_settings(state)
        assert payload["site_name"] == "CloudSite"
        assert payload["share_image_url"] == ""

        updated = await update_admin_site_settings(
            state,
            values={
                "site_name": "Boundary Site",
                "registration_enabled": False,
            },
        )
        assert updated["ok"] is True
        assert updated["site_name"] == "Boundary Site"
        assert updated["registration_enabled"] is False

        row = await state.get(SiteSettings, 1)
        assert row is not None
        assert row.site_name == "Boundary Site"

        old_name = await replace_share_page_image_name(
            state,
            new_name="share-page-test.png",
        )
        assert old_name == ""
        assert (
            await get_admin_site_settings(state)
        )["share_image_url"] == "/api/public/share-page/image"

        removed = await clear_share_page_image_name(state)
        assert removed == "share-page-test.png"
        assert (
            await get_admin_site_settings(state)
        )["share_image_url"] == ""

    await engine.dispose()
