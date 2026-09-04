"""轻量公开站点配置。

0.5.1 只提供页面真正使用的文本配置与注册开关。Branding 文件上传延期，
避免在整改版本继续扩张文件生命周期与备份范围。
"""

from fastapi import APIRouter

from .database import StateSession
from .models import SiteSettings


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
    }


@router.get("/api/site")
async def public_site():
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1)
        return public_site_settings(row)
