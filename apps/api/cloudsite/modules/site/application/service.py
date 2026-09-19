"""Site settings lifecycle and persistence-neutral projections."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .... import __version__
from ....platform.observability import write_operation_log
from ..infrastructure.models import SiteSettings


def public_site_settings_payload(
    row: SiteSettings | None,
) -> dict[str, Any]:
    if row is None:
        return {
            "site_name": "CloudSite",
            "home_title": "把网盘变成好看的资源网站",
            "hero_title": "把网盘变成好看的资源网站",
            "description": "",
            "site_tagline": "",
            "hero_subtitle": "",
            "footer_text": "",
            "submission_email": "nathxo@outlook.com",
            "github_url": "",
            "registration_enabled": True,
            "default_share_duration": "24h",
            "version": __version__,
        }
    home_title = row.home_title or "把网盘变成好看的资源网站"
    return {
        "site_name": row.site_name or "CloudSite",
        "home_title": home_title,
        "hero_title": home_title,
        "description": row.description or "",
        "site_tagline": row.description or "",
        "hero_subtitle": row.hero_subtitle or "",
        "footer_text": row.footer_text or "",
        "submission_email": row.submission_email or "nathxo@outlook.com",
        "github_url": row.github_url or "",
        "registration_enabled": bool(row.registration_enabled),
        "default_share_duration": row.default_share_duration or "24h",
        "version": __version__,
    }


def admin_site_settings_payload(
    row: SiteSettings,
) -> dict[str, Any]:
    return {
        **public_site_settings_payload(row),
        "share_image_url": (
            "/api/public/share-page/image"
            if row.share_image_name
            else ""
        ),
    }


async def public_site_settings(
    state: AsyncSession,
) -> dict[str, Any]:
    return public_site_settings_payload(
        await state.get(SiteSettings, 1)
    )


async def get_admin_site_settings(
    state: AsyncSession,
) -> dict[str, Any]:
    row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
    return admin_site_settings_payload(row)


async def update_admin_site_settings(
    state: AsyncSession,
    *,
    values: dict[str, Any],
) -> dict[str, Any]:
    row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
    changed: list[str] = []
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed.append(key)
    state.add(row)
    await write_operation_log(
        state,
        module="site",
        action="site_settings_updated",
        message=f"更新站点设置：{', '.join(changed) or '无变化'}",
    )
    await state.commit()
    return {"ok": True, **admin_site_settings_payload(row)}


async def replace_share_page_image_name(
    state: AsyncSession,
    *,
    new_name: str,
) -> str:
    row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
    old_name = row.share_image_name or ""
    row.share_image_name = new_name
    state.add(row)
    await state.commit()
    return old_name


async def clear_share_page_image_name(
    state: AsyncSession,
) -> str:
    row = await state.get(SiteSettings, 1)
    old_name = row.share_image_name if row else ""
    if row is not None:
        row.share_image_name = ""
        await state.commit()
    return old_name


async def home_site_settings(
    state: AsyncSession,
) -> dict[str, Any]:
    row = await state.get(SiteSettings, 1)
    return {
        "site_name": (row.site_name if row else "") or "CloudSite",
        "home_title": (
            (row.home_title if row else "")
            or "把网盘变成好看的资源网站"
        ),
        "description": (row.description if row else "") or "",
        "recent_limit": int(row.recent_limit if row else 6),
        "popular_limit": int(row.popular_limit if row else 6),
        "collection_limit": int(row.collection_limit if row else 4),
        "popular_strategy": (
            (row.popular_strategy if row else "") or "recent"
        ),
    }


async def share_page_settings_payload(
    state: AsyncSession,
) -> dict[str, str]:
    row = await state.get(SiteSettings, 1)
    return {
        "site_name": (row.site_name if row else "") or "CloudSite",
        "share_image_url": (
            "/api/public/share-page/image"
            if row and row.share_image_name
            else ""
        ),
    }


async def share_page_image_name(
    state: AsyncSession,
) -> str:
    row = await state.get(SiteSettings, 1)
    return row.share_image_name if row else ""


async def registration_enabled(
    state: AsyncSession,
) -> bool:
    row = await state.get(SiteSettings, 1)
    return True if row is None else bool(row.registration_enabled)


__all__ = [
    "admin_site_settings_payload",
    "clear_share_page_image_name",
    "get_admin_site_settings",
    "home_site_settings",
    "public_site_settings",
    "public_site_settings_payload",
    "registration_enabled",
    "replace_share_page_image_name",
    "share_page_image_name",
    "share_page_settings_payload",
    "update_admin_site_settings",
]
