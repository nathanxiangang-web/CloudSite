"""轻量公开站点配置。

0.5.1 只提供页面真正使用的文本配置与注册开关。Branding 文件上传延期，
避免在整改版本继续扩张文件生命周期与备份范围。
"""

from fastapi import APIRouter
from sqlalchemy import select, func

from . import __version__
from .database import StateSession, IndexSession
from .models import ContentRootMapping, Resource, SiteSettings


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
        return result
