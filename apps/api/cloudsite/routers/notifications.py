"""notifications 路由：用户通知。"""
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, or_, select

from ..auth import require_user, validate_request_origin
from ..models import Notification, utcnow
from ..services.notifications import notification_dict

router = APIRouter()


@router.get("/api/notifications")
async def list_notifications(request: Request):
    from ..main import StateSession

    async with StateSession() as state:
        _, user = await require_user(state, request)
        now = utcnow()
        query = (
            select(Notification)
            .where(
                Notification.enabled == True,
                or_(Notification.user_id == None, Notification.user_id == user.id),
                or_(Notification.expires_at == None, Notification.expires_at > now),
            )
            .order_by(desc(Notification.pinned), desc(Notification.published_at))
            .limit(30)
        )
        rows = list((await state.scalars(query)).all())
        await state.commit()
        return {"items": [notification_dict(row) for row in rows]}


@router.delete("/api/notifications/{notification_id}")
async def delete_my_notification(notification_id: int, request: Request):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        row = await state.get(Notification, notification_id)
        if not row:
            raise HTTPException(404, "通知不存在")
        if row.user_id != user.id:
            raise HTTPException(403, "只能删除发给自己的通知")
        await state.delete(row)
        await state.commit()
        return {"ok": True}
