"""Regression coverage for Site module ownership and settings contracts."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import SiteSettings as LegacySiteSettings
from cloudsite.modules.site.contracts.public import (
    clear_share_page_image_name,
    get_admin_site_settings,
    home_site_settings,
    registration_enabled,
    replace_share_page_image_name,
    share_page_settings_payload,
    update_admin_site_settings,
)
from cloudsite.modules.site.infrastructure.models import (
    SiteSettings as ModuleSiteSettings,
)


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_site_settings_model_is_module_owned():
    assert LegacySiteSettings is ModuleSiteSettings


async def test_site_settings_persist_behind_public_contract():
    engine, factory = await _store()
    async with factory() as state:
        assert await registration_enabled(state) is True

        payload = await get_admin_site_settings(state)
        assert payload["site_name"] == "CloudSite"
        assert payload["share_image_url"] == ""

        updated = await update_admin_site_settings(
            state,
            values={
                "site_name": "Boundary Site",
                "registration_enabled": False,
                "recent_limit": 9,
                "popular_strategy": "manual",
            },
        )
        assert updated["ok"] is True
        assert updated["site_name"] == "Boundary Site"
        assert updated["registration_enabled"] is False
        assert await registration_enabled(state) is False

        home = await home_site_settings(state)
        assert home["site_name"] == "Boundary Site"
        assert home["recent_limit"] == 9
        assert home["popular_strategy"] == "manual"

        old_name = await replace_share_page_image_name(
            state,
            new_name="share-page-test.png",
        )
        assert old_name == ""
        assert (
            await share_page_settings_payload(state)
        )["share_image_url"] == "/api/public/share-page/image"

        removed = await clear_share_page_image_name(state)
        assert removed == "share-page-test.png"
        assert (
            await get_admin_site_settings(state)
        )["share_image_url"] == ""

    await engine.dispose()
