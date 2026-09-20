"""notifications 路由：用户通知。"""

from fastapi import APIRouter, HTTPException, Request

from ..auth import require_user, validate_request_origin
from ..modules.notifications.contracts.public import (
    NotificationForbidden,
    NotificationNotFound,
    delete_notification_for_user,
    list_notifications_for_user,
)

router = APIRouter()


@router.get("/api/notifications")
async def list_notifications(request: Request):
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        items = await list_notifications_for_user(
            state,
            user_id=user.id,
            limit=30,
        )
        return {"items": items}


@router.delete("/api/notifications/{notification_id}")
async def delete_my_notification(notification_id: int, request: Request):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        try:
            await delete_notification_for_user(
                state,
                notification_id=notification_id,
                user_id=user.id,
            )
        except NotificationNotFound as exc:
            raise HTTPException(404, "通知不存在") from exc
        except NotificationForbidden as exc:
            raise HTTPException(403, "只能删除发给自己的通知") from exc
        return {"ok": True}
