"""Compatibility facade for Shares target/scope helpers."""

from datetime import datetime, timezone

from fastapi import HTTPException

from ..modules.shares.contracts.public import (
    MAX_SHARE_DOWNLOADS,
    ShareNotFound,
    ShareValidationError,
    build_share_target_payload as _build_share_target_payload,
    get_owned_share,
    resolve_share_download_resource as _resolve_share_download_resource,
    share_payload,
)


def share_dict(row) -> dict:
    return share_payload(row)


def share_is_expired(row) -> bool:
    if not row.expires_at:
        return False
    expires_at = (
        row.expires_at
        if row.expires_at.tzinfo
        else row.expires_at.replace(tzinfo=timezone.utc)
    )
    return expires_at <= datetime.now(timezone.utc)


def _http_error(exc: ShareValidationError) -> HTTPException:
    return HTTPException(
        exc.status_code,
        {"code": exc.code, "message": exc.message},
    )


async def build_share_target_payload(state, index, row) -> dict:
    try:
        return await _build_share_target_payload(state, index, row)
    except ShareValidationError as exc:
        raise _http_error(exc) from exc


async def resolve_share_download_resource(
    state,
    index,
    row,
    resource_id: str | None,
):
    try:
        return await _resolve_share_download_resource(
            state,
            index,
            row,
            resource_id,
        )
    except ShareValidationError as exc:
        raise _http_error(exc) from exc


async def owned_share(state, token: str, user_id: int):
    try:
        return await get_owned_share(
            state,
            token,
            owner_user_id=user_id,
        )
    except ShareNotFound as exc:
        raise HTTPException(
            404,
            {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
        ) from exc


__all__ = [
    "MAX_SHARE_DOWNLOADS",
    "build_share_target_payload",
    "owned_share",
    "resolve_share_download_resource",
    "share_dict",
    "share_is_expired",
]
