"""Public Site composition and compatibility facade.

SiteSettings persistence is owned by modules/site. This root module keeps the
legacy import surface and composes the public /api/site payload from owner
contracts.
"""

from fastapi import APIRouter

from .database import IndexSession, StateSession
from .modules.presentation.contracts.public import public_presentation
from .modules.providers.contracts.public import enabled_root_ids
from .modules.resources.contracts.public import resource_queries
from .modules.site.contracts.public import (
    admin_site_settings_payload,
    clear_share_page_image_name,
    get_admin_site_settings,
    home_site_settings,
    public_site_settings as get_public_site_settings,
    public_site_settings_payload,
    registration_enabled,
    replace_share_page_image_name,
    share_page_image_name,
    share_page_settings_payload,
    update_admin_site_settings,
)


router = APIRouter(tags=["site"])
_CONTENT_TYPES = ("software", "image", "video", "document", "file")

# Compatibility name used by historical tests/helpers that pass a settings row.
public_site_settings = public_site_settings_payload


@router.get("/api/site")
async def public_site():
    async with StateSession() as state, IndexSession() as index:
        result = await get_public_site_settings(state)
        roots = await enabled_root_ids(state)
        result["content_counts"] = (
            await resource_queries(index).browse_resource_counts(
                enabled_root_ids=roots,
                status="active",
                content_types=_CONTENT_TYPES,
            )
        )
        presentation = await public_presentation(state)
        result["presentation"] = {
            "enabled": presentation["enabled"],
            "preset": presentation["preset"],
            "theme_tokens": presentation["theme_tokens"],
            "navigation": presentation["navigation"],
        }
        return result


__all__ = [
    "admin_site_settings_payload",
    "clear_share_page_image_name",
    "get_admin_site_settings",
    "home_site_settings",
    "public_site_settings",
    "public_site",
    "registration_enabled",
    "replace_share_page_image_name",
    "share_page_image_name",
    "share_page_settings_payload",
    "update_admin_site_settings",
]
