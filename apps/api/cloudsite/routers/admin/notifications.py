"""admin/notifications 路由：通知管理。"""

from fastapi import APIRouter, HTTPException

from ...modules.notifications.contracts.public import (
    NotificationNotFound,
    create_admin_notification,
    delete_admin_notification,
    list_admin_notifications,
    update_admin_notification,
)
from ...schemas import NotificationInput, NotificationUpdate

router = APIRouter()


@router.get("/api/admin/notifications")
async def admin_notifications():
    from ...main import StateSession

    async with StateSession() as state:
        return {"items": await list_admin_notifications(state)}


@router.post("/api/admin/notifications")
async def create_notification(payload: NotificationInput):
    from ...main import StateSession

    async with StateSession() as state:
        return await create_admin_notification(
            state,
            title=payload.title,
            body=payload.body,
            level=payload.level,
            pinned=payload.pinned,
            enabled=payload.enabled,
            expires_at=payload.expires_at,
        )


@router.patch("/api/admin/notifications/{notification_id}")
async def update_notification(
    notification_id: int,
    payload: NotificationUpdate,
):
    from ...main import StateSession

    changes = {
        field: getattr(payload, field)
        for field in payload.model_fields_set
        if field in {
            "title",
            "body",
            "level",
            "pinned",
            "enabled",
            "expires_at",
        }
    }
    async with StateSession() as state:
        try:
            return await update_admin_notification(
                state,
                notification_id=notification_id,
                changes=changes,
            )
        except NotificationNotFound as exc:
            raise HTTPException(404, "通知不存在") from exc


@router.delete("/api/admin/notifications/{notification_id}")
async def delete_notification(notification_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await delete_admin_notification(
                state,
                notification_id=notification_id,
            )
        except NotificationNotFound as exc:
            raise HTTPException(404, "通知不存在") from exc
        return {"ok": True}
