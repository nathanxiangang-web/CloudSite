"""notifications application 服务：通知序列化辅助函数。"""
from ....models import Notification


def notification_dict(row: Notification) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "title": row.title,
        "body": row.body,
        "level": row.level,
        "pinned": row.pinned,
        "enabled": row.enabled,
        "source": row.source,
        "published_at": row.published_at,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }