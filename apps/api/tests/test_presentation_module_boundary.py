"""Regression coverage for the Presentation module boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import SitePresentation as LegacySitePresentation
from cloudsite.modules.presentation.contracts.public import (
    PresentationConfig,
    get_admin_presentation,
    public_presentation,
    rollback_admin_presentation,
    save_admin_presentation,
    toggle_admin_presentation,
)
from cloudsite.modules.presentation.infrastructure.models import (
    SitePresentation as ModuleSitePresentation,
)
from cloudsite.services.presentation import (
    PresentationConfig as LegacyPresentationConfig,
)


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_legacy_presentation_surfaces_reexport_module_owners():
    assert LegacySitePresentation is ModuleSitePresentation
    assert LegacyPresentationConfig is PresentationConfig


async def test_presentation_lifecycle_and_public_projection():
    engine, factory = await _store()
    async with factory() as state:
        initial = await get_admin_presentation(state)
        assert initial["enabled"] is False
        assert initial["config_revision"] == 1

        first = await save_admin_presentation(
            state,
            cfg=PresentationConfig(
                preset="custom",
                home_blocks=[
                    {
                        "type": "featured",
                        "sort_order": 0,
                        "title": "精选",
                    }
                ],
            ),
            summary="first",
        )
        assert first["config_revision"] == 2

        second = await save_admin_presentation(
            state,
            cfg=PresentationConfig(
                preset="custom",
                home_blocks=[
                    {
                        "type": "recent",
                        "sort_order": 0,
                        "title": "最近",
                    }
                ],
            ),
            summary="second",
        )
        assert second["config_revision"] == 3

        current = await get_admin_presentation(state)
        assert current["revisions"]
        revision = current["revisions"][0]
        assert revision["revision"] == 2

        rolled = await rollback_admin_presentation(
            state,
            revision_id=revision["revision_id"],
        )
        assert rolled["config_revision"] == 4
        assert (
            rolled["config"]["home_blocks"][0]["type"]
            == "featured"
        )

        enabled = await toggle_admin_presentation(
            state,
            enabled=True,
        )
        assert enabled == {"ok": True, "enabled": True}

        public = await public_presentation(state)
        assert public["enabled"] is True
        assert public["ordered_blocks"][0]["type"] == "featured"

    await engine.dispose()
