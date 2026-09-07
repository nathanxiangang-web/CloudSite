"""admin/site 路由：站点设置与分享图。"""
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ...auth import validate_request_origin
from ...models import OperationLog, SiteSettings
from ...schemas import SiteSettingsUpdate
from ...site import public_site_settings
from ...site_assets import SHARE_IMAGE_MAX_BYTES, remove_share_image, save_share_image

router = APIRouter()


def site_settings_dict(row: SiteSettings) -> dict:
    return {
        **public_site_settings(row),
        "share_image_url": "/api/public/share-page/image" if row.share_image_name else "",
    }


@router.get("/api/admin/site")
async def get_site():
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
        return site_settings_dict(row)


@router.put("/api/admin/site")
async def save_site(payload: SiteSettingsUpdate, request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
        changed: list[str] = []
        for key, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed.append(key)
        session.add(row)
        session.add(
            OperationLog(
                level="INFO",
                module="site",
                action="site_settings_updated",
                message=f"更新站点设置：{', '.join(changed) or '无变化'}",
            )
        )
        await session.commit()
        return {"ok": True, **site_settings_dict(row)}


@router.post("/api/admin/site/share-image")
async def upload_share_page_image(request: Request, file: UploadFile = File(...)):
    from ...main import StateSession

    validate_request_origin(request)
    data = await file.read(SHARE_IMAGE_MAX_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(400, {"code": "SHARE_IMAGE_EMPTY", "message": "请选择图片文件"})
    if len(data) > SHARE_IMAGE_MAX_BYTES:
        raise HTTPException(413, {"code": "SHARE_IMAGE_TOO_LARGE", "message": "图片不能超过 8MB"})
    try:
        new_name = save_share_image(data)
    except ValueError as exc:
        raise HTTPException(400, {"code": "SHARE_IMAGE_INVALID", "message": str(exc)}) from exc
    old_name = ""
    try:
        async with StateSession() as session:
            row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
            old_name = row.share_image_name or ""
            row.share_image_name = new_name
            session.add(row)
            await session.commit()
    except Exception:
        remove_share_image(new_name)
        raise
    if old_name and old_name != new_name:
        remove_share_image(old_name)
    return {"ok": True, "share_image_url": "/api/public/share-page/image"}


@router.delete("/api/admin/site/share-image")
async def delete_share_page_image(request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1)
        old_name = row.share_image_name if row else ""
        if row:
            row.share_image_name = ""
            await session.commit()
    if old_name:
        remove_share_image(old_name)
    return {"ok": True}