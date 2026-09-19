"""轻量公开站点配置。

0.5.1 只提供页面真正使用的文本配置与注册开关。Branding 文件上传延期，
避免在整改版本继续扩张文件生命周期与备份范围。
"""

from fastapi import APIRouter
from sqlalchemy import select, func

from . import __version__
from .database import StateSession, IndexSession
from .models import ContentRootMapping, Resource, SitePresentation, SiteSettings
from .platform.observability import write_operation_log


from .services.presentation import default_presentation, validate_config

router = APIRouter(tags=["site"])

def public_site_settings(row: SiteSettings | None) -> dict:
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
    return {
        "site_name": row.site_name or "CloudSite",
        "home_title": row.home_title or "把网盘变成好看的资源网站",
        "hero_title": row.home_title or "把网盘变成好看的资源网站",
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


def admin_site_settings_payload(row: SiteSettings) -> dict:
    return {
        **public_site_settings(row),
        "share_image_url": (
            "/api/public/share-page/image"
            if row.share_image_name
            else ""
        ),
    }


async def get_admin_site_settings(state) -> dict:
    row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
    return admin_site_settings_payload(row)


async def update_admin_site_settings(
    state,
    *,
    values: dict,
) -> dict:
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
    state,
    *,
    new_name: str,
) -> str:
    row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
    old_name = row.share_image_name or ""
    row.share_image_name = new_name
    state.add(row)
    await state.commit()
    return old_name


async def clear_share_page_image_name(state) -> str:
    row = await state.get(SiteSettings, 1)
    old_name = row.share_image_name if row else ""
    if row is not None:
        row.share_image_name = ""
        await state.commit()
    return old_name


async def share_page_settings_payload(state) -> dict:
    row = await state.get(SiteSettings, 1)
    return {
        "site_name": (row.site_name if row else "") or "CloudSite",
        "share_image_url": (
            "/api/public/share-page/image"
            if row and row.share_image_name
            else ""
        ),
    }


async def share_page_image_name(state) -> str:
    row = await state.get(SiteSettings, 1)
    return row.share_image_name if row else ""


@router.get("/api/site")
async def public_site():
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(SiteSettings, 1)
        result = public_site_settings(row)
        # 内容数量：供前端导航在 0 篇教程时隐藏教程入口
        enabled_ids = set((await state.scalars(select(ContentRootMapping.id).where(ContentRootMapping.enabled.is_(True)))).all())
        scope = Resource.root_mapping_id.in_(enabled_ids) if enabled_ids else False
        counts = {ct: 0 for ct in ("software", "image", "video", "document", "file")}
        for r in (await index.execute(select(Resource.content_type, func.count()).select_from(Resource).where(Resource.status == "active", scope).group_by(Resource.content_type))).all():
            if r[0] in counts:
                counts[r[0]] = int(r[1] or 0)
        result["content_counts"] = counts
        # B1 站点呈现：导航组合与主题变量，供前台动态导航与主题
        presentation_row = await state.get(SitePresentation, 1)
        if presentation_row and presentation_row.enabled:
            cfg = validate_config(presentation_row.preset, presentation_row.theme_tokens_json, presentation_row.navigation_json, presentation_row.home_blocks_json)
            result["presentation"] = {
                "enabled": True,
                "preset": cfg.preset,
                "theme_tokens": cfg.theme_tokens.model_dump(),
                "navigation": [item.model_dump() for item in cfg.navigation],
            }
        else:
            _default_cfg = default_presentation()
            result["presentation"] = {
                "enabled": False,
                "preset": _default_cfg.preset,
                "theme_tokens": _default_cfg.theme_tokens.model_dump(),
                "navigation": [item.model_dump() for item in _default_cfg.navigation],
            }
        return result
