"""C4 资源关注路由：登录用户关注/取关 catalog 条目、我的关注列表、退订。

所有路由要求登录用户（require_user），私有关系。遵循现有认证与 origin 校验模式。
"""
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from ..auth import require_user, validate_request_origin
from ..models import CatalogEntry
from ..services.catalog_follow import (
    CatalogEntryNotFollowable,
    follow_entry,
    get_follow_status,
    list_my_follows,
    set_subscription_notify,
    unfollow_entry,
)

router = APIRouter()


def _follow_error(exc: CatalogEntryNotFollowable) -> HTTPException:
    if exc.reason == "entry_not_found":
        return HTTPException(
            404,
            {"code": "CATALOG_ENTRY_NOT_FOUND", "message": "条目不存在或未发布"},
        )
    return HTTPException(409, {"code": "CATALOG_FOLLOW_CONFLICT", "message": "关注操作冲突"})


class SubscriptionUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notify_enabled: bool


@router.post("/api/me/catalog/favorites/{entry_id}", status_code=200)
async def follow_catalog_entry(entry_id: str, request: Request):
    validate_request_origin(request)
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        try:
            result = await follow_entry(state, user_id=user.id, entry_id=entry_id)
        except CatalogEntryNotFollowable as exc:
            raise _follow_error(exc) from exc
        await state.commit()
        return {"ok": True, "favorited": result.favorited, "notify_enabled": result.notify_enabled}


@router.delete("/api/me/catalog/favorites/{entry_id}")
async def unfollow_catalog_entry(entry_id: str, request: Request):
    validate_request_origin(request)
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        result = await unfollow_entry(state, user_id=user.id, entry_id=entry_id)
        await state.commit()
        return {"ok": True, "favorited": result.favorited, "notify_enabled": result.notify_enabled}


@router.get("/api/me/catalog/favorites/{entry_id}")
async def catalog_favorite_status(entry_id: str, request: Request):
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        result = await get_follow_status(state, user_id=user.id, entry_id=entry_id)
        await state.commit()
        return {"favorited": result.favorited, "notify_enabled": result.notify_enabled}


@router.patch("/api/me/catalog/favorites/{entry_id}")
async def update_catalog_subscription(entry_id: str, payload: SubscriptionUpdateInput, request: Request):
    validate_request_origin(request)
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        result = await set_subscription_notify(
            state,
            user_id=user.id,
            entry_id=entry_id,
            notify_enabled=payload.notify_enabled,
        )
        await state.commit()
        return {"ok": True, "favorited": result.favorited, "notify_enabled": result.notify_enabled}


@router.get("/api/me/catalog/favorites")
async def list_my_catalog_favorites(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        result = await list_my_follows(
            state,
            user_id=user.id,
            page=page,
            page_size=page_size,
        )
        await state.commit()
        return {
            "items": result.items,
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "total_pages": result.total_pages,
        }
