"""用户收藏 / 浏览历史 / 视频播放进度 API（/api/me/*）。

所有关系只引用 Stable Resource ID，不引用 Path。读取列表时始终过滤
Publication Scope，避免通过用户态绕过已停用 Root 或历史脏索引。
"""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .auth import require_user, validate_request_origin
from .database import IndexSession, StateSession
from .models import Resource, UserFavorite, UserPlaybackProgress, UserResourceHistory, utcnow
from .schemas import PlaybackProgressInput
from .shares.service import enabled_root_ids, resource_in_publication_scope


router = APIRouter(prefix="/api/me", tags=["user-data"])

HISTORY_TOUCH_INTERVAL_SECONDS = 300
HISTORY_MAX_PER_USER = 500
PROGRESS_MIN_POSITION_SECONDS = 5
COMPLETED_RATIO = 0.90
COMPLETED_REMAINING_SECONDS = 30


def _resource_not_found() -> HTTPException:
    return HTTPException(404, {"code": "RESOURCE_NOT_AVAILABLE", "message": "资源不存在或不可用"})


def _resource_summary(row: Resource) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "content_type": row.content_type,
        "extension": row.extension,
        "mime_type": row.mime_type,
        "size": row.size,
        "modified_at": row.modified_at,
        "thumbnail": row.thumbnail,
    }


async def _visible_resources(state, index, resource_ids: list[str]) -> dict[str, Resource]:
    if not resource_ids:
        return {}
    roots = await enabled_root_ids(state)
    if not roots:
        return {}
    rows = list(
        (
            await index.scalars(
                select(Resource).where(
                    Resource.id.in_(resource_ids),
                    Resource.status == "active",
                    Resource.root_mapping_id.in_(roots),
                )
            )
        ).all()
    )
    return {row.id: row for row in rows}


def _compute_completed(position: int, duration: int) -> bool:
    if duration <= 0:
        return False
    remaining_threshold = min(COMPLETED_REMAINING_SECONDS, duration * (1 - COMPLETED_RATIO))
    return position / duration >= COMPLETED_RATIO or (duration - position) <= remaining_threshold


# ── 收藏 ────────────────────────────────────────────────────────────────────

@router.post("/favorites/{resource_id}", status_code=201)
async def add_favorite(resource_id: str, request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            resource = await index.get(Resource, resource_id)
            if not await resource_in_publication_scope(state, resource):
                raise _resource_not_found()
        existing = await state.scalar(
            select(UserFavorite).where(UserFavorite.user_id == user.id, UserFavorite.resource_id == resource_id)
        )
        if existing is None:
            state.add(UserFavorite(user_id=user.id, resource_id=resource_id))
            try:
                await state.commit()
            except IntegrityError:
                await state.rollback()
        return {"ok": True, "favorited": True}


@router.delete("/favorites/{resource_id}")
async def remove_favorite(resource_id: str, request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await state.execute(
            delete(UserFavorite).where(UserFavorite.user_id == user.id, UserFavorite.resource_id == resource_id)
        )
        await state.commit()
        return {"ok": True, "favorited": False}


@router.get("/favorites/{resource_id}")
async def favorite_status(resource_id: str, request: Request):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        favorited = await state.scalar(
            select(UserFavorite.id).where(
                UserFavorite.user_id == user.id,
                UserFavorite.resource_id == resource_id,
            )
        )
        return {"favorited": favorited is not None}


@router.get("/favorites")
async def list_favorites(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        favorites = list(
            (
                await state.scalars(
                    select(UserFavorite)
                    .where(UserFavorite.user_id == user.id)
                    .order_by(UserFavorite.created_at.desc(), UserFavorite.id.desc())
                )
            ).all()
        )
        async with IndexSession() as index:
            by_id = await _visible_resources(state, index, [item.resource_id for item in favorites])
    items: list[dict] = []
    unavailable = 0
    for item in favorites:
        resource = by_id.get(item.resource_id)
        if resource is None:
            unavailable += 1
            continue
        items.append({**_resource_summary(resource), "favorited_at": item.created_at})
    start = (max(1, page) - 1) * max(1, page_size)
    return {"items": items[start : start + max(1, page_size)], "total": len(items), "unavailable_count": unavailable}


# ── 浏览历史 ────────────────────────────────────────────────────────────────

@router.post("/history/{resource_id}/touch", status_code=204)
async def touch_history(resource_id: str, request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            resource = await index.get(Resource, resource_id)
            if not await resource_in_publication_scope(state, resource):
                raise _resource_not_found()
        now = utcnow()
        row = await state.scalar(
            select(UserResourceHistory).where(
                UserResourceHistory.user_id == user.id,
                UserResourceHistory.resource_id == resource_id,
            )
        )
        if row is None:
            state.add(UserResourceHistory(user_id=user.id, resource_id=resource_id, view_count=1, first_viewed_at=now, last_viewed_at=now))
        else:
            previous_viewed_at = row.last_viewed_at or now
            if previous_viewed_at.tzinfo is None:
                previous_viewed_at = previous_viewed_at.replace(tzinfo=timezone.utc)
            since_last = (now - previous_viewed_at).total_seconds()
            if since_last < HISTORY_TOUCH_INTERVAL_SECONDS:
                await state.commit()
                return None
            row.last_viewed_at = now
            row.view_count = (row.view_count or 0) + 1
            row.updated_at = now
        await state.commit()
        # 事务内裁剪最旧项，避免无限增长
        await _prune_history(state, user.id)
        await state.commit()
        return None


async def _prune_history(state, user_id: int) -> None:
    count = int(
        await state.scalar(select(func.count()).select_from(UserResourceHistory).where(UserResourceHistory.user_id == user_id))
        or 0
    )
    if count <= HISTORY_MAX_PER_USER:
        return
    oldest_ids = list(
        (
            await state.scalars(
                select(UserResourceHistory.id)
                .where(UserResourceHistory.user_id == user_id)
                .order_by(UserResourceHistory.last_viewed_at.asc(), UserResourceHistory.id.asc())
                .limit(count - HISTORY_MAX_PER_USER)
            )
        ).all()
    )
    if oldest_ids:
        await state.execute(delete(UserResourceHistory).where(UserResourceHistory.id.in_(oldest_ids)))


@router.get("/history")
async def list_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        rows = list(
            (
                await state.scalars(
                    select(UserResourceHistory)
                    .where(UserResourceHistory.user_id == user.id)
                    .order_by(UserResourceHistory.last_viewed_at.desc(), UserResourceHistory.id.desc())
                )
            ).all()
        )
        async with IndexSession() as index:
            by_id = await _visible_resources(state, index, [item.resource_id for item in rows])
    items: list[dict] = []
    unavailable = 0
    for item in rows:
        resource = by_id.get(item.resource_id)
        if resource is None:
            unavailable += 1
            continue
        items.append(
            {
                **_resource_summary(resource),
                "last_viewed_at": item.last_viewed_at,
                "view_count": item.view_count,
            }
        )
    start = (max(1, page) - 1) * max(1, page_size)
    return {"items": items[start : start + max(1, page_size)], "total": len(items), "unavailable_count": unavailable}


@router.delete("/history/{resource_id}")
async def remove_history(resource_id: str, request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await state.execute(
            delete(UserResourceHistory).where(UserResourceHistory.user_id == user.id, UserResourceHistory.resource_id == resource_id)
        )
        await state.commit()
        return {"ok": True}


@router.delete("/history")
async def clear_history(request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await state.execute(delete(UserResourceHistory).where(UserResourceHistory.user_id == user.id))
        await state.commit()
        return {"ok": True}


# ── 播放进度 ────────────────────────────────────────────────────────────────

@router.get("/playback/{resource_id}")
async def get_playback(resource_id: str, request: Request):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            resource = await index.get(Resource, resource_id)
            if not await resource_in_publication_scope(state, resource):
                raise _resource_not_found()
        row = await state.scalar(
            select(UserPlaybackProgress).where(
                UserPlaybackProgress.user_id == user.id,
                UserPlaybackProgress.resource_id == resource_id,
            )
        )
        if row is None:
            return {"position_seconds": 0, "duration_seconds": 0, "completed": False}
        return {
            "position_seconds": row.position_seconds,
            "duration_seconds": row.duration_seconds,
            "completed": row.completed,
            "last_played_at": row.last_played_at,
        }


@router.put("/playback/{resource_id}")
async def save_playback(resource_id: str, payload: PlaybackProgressInput, request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            resource = await index.get(Resource, resource_id)
            if not await resource_in_publication_scope(state, resource):
                raise _resource_not_found()
        now = utcnow()
        row = await state.scalar(
            select(UserPlaybackProgress).where(
                UserPlaybackProgress.user_id == user.id,
                UserPlaybackProgress.resource_id == resource_id,
            )
        )
        completed = _compute_completed(payload.position_seconds, payload.duration_seconds)
        if row is None:
            if payload.position_seconds < PROGRESS_MIN_POSITION_SECONDS and not completed:
                return {"ok": True, "saved": False}
            state.add(
                UserPlaybackProgress(
                    user_id=user.id,
                    resource_id=resource_id,
                    position_seconds=payload.position_seconds,
                    duration_seconds=payload.duration_seconds,
                    completed=completed,
                    last_played_at=now,
                )
            )
        else:
            # 0.5.1 采用 Last Write Wins；用户从头播放时允许保存较小进度。
            row.position_seconds = payload.position_seconds
            row.duration_seconds = payload.duration_seconds
            row.completed = completed
            row.last_played_at = now
            row.updated_at = now
        try:
            await state.commit()
        except IntegrityError:
            await state.rollback()
        return {"ok": True, "saved": True, "completed": completed}


@router.delete("/playback/{resource_id}")
async def reset_playback(resource_id: str, request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await state.execute(
            delete(UserPlaybackProgress).where(
                UserPlaybackProgress.user_id == user.id,
                UserPlaybackProgress.resource_id == resource_id,
            )
        )
        await state.commit()
        return {"ok": True}


@router.get("/playback")
async def list_playback(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        rows = list(
            (
                await state.scalars(
                    select(UserPlaybackProgress)
                    .where(UserPlaybackProgress.user_id == user.id, UserPlaybackProgress.completed.is_(False))
                    .order_by(UserPlaybackProgress.last_played_at.desc(), UserPlaybackProgress.id.desc())
                )
            ).all()
        )
        async with IndexSession() as index:
            by_id = await _visible_resources(state, index, [item.resource_id for item in rows])
    items = []
    unavailable = 0
    for item in rows:
        resource = by_id.get(item.resource_id)
        if resource is None:
            unavailable += 1
            continue
        items.append(
            {
                **_resource_summary(resource),
                "position_seconds": item.position_seconds,
                "duration_seconds": item.duration_seconds,
                "last_played_at": item.last_played_at,
            }
        )
    start = (page - 1) * page_size
    return {"items": items[start : start + page_size], "total": len(items), "unavailable_count": unavailable}
