"""admin/notifications 路由：通知管理。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from ...models import Notification, OperationLog, utcnow
from ...schemas import NotificationInput, NotificationUpdate
from ...services.notifications import notification_dict

router = APIRouter()


@router.get("/api/admin/notifications")
async def admin_notifications():
    from ...main import StateSession

    async with StateSession() as state:
        rows = list((await state.scalars(select(Notification).order_by(desc(Notification.created_at)))).all())
        await state.commit()
        return {"items": [notification_dict(row) for row in rows]}


@router.post("/api/admin/notifications")
async def create_notification(payload: NotificationInput):
    from ...main import StateSession

    async with StateSession() as state:
        row = Notification(
            title=payload.title,
            body=payload.body,
            level=payload.level,
            pinned=payload.pinned,
            enabled=payload.enabled,
            source="manual",
            expires_at=payload.expires_at,
        )
        state.add(row)
        state.add(OperationLog(level="INFO", module="notification", action="notification_created", message=f"新建通知 {payload.title}"))
        await state.commit()
        await state.refresh(row)
        return notification_dict(row)


@router.patch("/api/admin/notifications/{notification_id}")
async def update_notification(notification_id: int, payload: NotificationUpdate):
    from ...main import StateSession

    async with StateSession() as state:
        row = await state.get(Notification, notification_id)
        if not row:
            raise HTTPException(404, "通知不存在")
        provided = payload.model_fields_set
        for field in ("title", "body", "level", "pinned", "expires_at"):
            if field in provided:
                setattr(row, field, getattr(payload, field))
        if "enabled" in provided:
            was_enabled = row.enabled
            row.enabled = payload.enabled
            if not was_enabled and payload.enabled:
                row.published_at = utcnow()
        state.add(OperationLog(level="INFO", module="notification", action="notification_updated", message=f"更新通知 #{row.id} {row.title}"))
        await state.commit()
        await state.refresh(row)
        return notification_dict(row)


@router.delete("/api/admin/notifications/{notification_id}")
async def delete_notification(notification_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        row = await state.get(Notification, notification_id)
        if not row:
            raise HTTPException(404, "通知不存在")
        state.add(OperationLog(level="INFO", module="notification", action="notification_deleted", message=f"删除通知 #{row.id} {row.title}"))
        await state.delete(row)
        await state.commit()
        return {"ok": True}