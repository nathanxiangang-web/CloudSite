"""submissions 服务：投稿序列化与 URL 校验辅助函数。"""
from urllib.parse import urlparse

from fastapi import HTTPException


def submission_dict(row, username: str) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": username,
        "resource_name": row.resource_name,
        "resource_type": row.resource_type,
        "description": row.description,
        "source_url": row.source_url,
        "download_url": row.download_url,
        "copyright_note": row.copyright_note,
        "note": row.note,
        "status": row.status,
        "admin_note": row.admin_note,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def validate_optional_http_url(value: str, field_name: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, f"{field_name} 必须是 http 或 https 链接")
    return value