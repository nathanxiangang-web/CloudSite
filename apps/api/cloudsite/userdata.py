"""User favorites / history / playback HTTP composition.

Users owns user-data persistence. Resource visibility and display metadata are
composed through Providers and Resources public contracts.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from .auth import require_user, validate_request_origin
from .database import IndexSession, StateSession
from .modules.providers.contracts.public import enabled_root_ids
from .modules.resources.contracts.public import (
    ResourceReferenceView,
    resource_queries,
)
from .modules.users.contracts.public import (
    COMPLETED_RATIO,
    COMPLETED_REMAINING_SECONDS,
    HISTORY_MAX_PER_USER,
    HISTORY_TOUCH_INTERVAL_SECONDS,
    PROGRESS_MIN_POSITION_SECONDS,
    add_favorite_record,
    clear_history_records,
    compute_playback_completed,
    favorite_record_exists,
    get_playback_record,
    list_favorite_records,
    list_history_records,
    list_incomplete_playback_records,
    remove_favorite_record,
    remove_history_record,
    reset_playback_record,
    save_playback_record,
    touch_history_record,
)
from .schemas import PlaybackProgressInput


router = APIRouter(prefix="/api/me", tags=["user-data"])

# Historical compatibility helper used by focused tests.
_compute_completed = compute_playback_completed


def _resource_not_found() -> HTTPException:
    return HTTPException(
        404,
        {
            "code": "RESOURCE_NOT_AVAILABLE",
            "message": "资源不存在或不可用",
        },
    )


def _resource_summary(
    row: ResourceReferenceView,
) -> dict:
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


async def _visible_resources(
    state,
    index,
    resource_ids: list[str],
) -> dict[str, ResourceReferenceView]:
    if not resource_ids:
        return {}
    roots = await enabled_root_ids(state)
    if not roots:
        return {}
    rows = await resource_queries(index).resource_references(
        resource_ids=resource_ids,
    )
    return {
        resource_id: row
        for resource_id, row in rows.items()
        if (
            row.status == "active"
            and row.root_mapping_id is not None
            and row.root_mapping_id in roots
        )
    }


async def _require_visible_resource(
    state,
    index,
    resource_id: str,
) -> ResourceReferenceView:
    rows = await _visible_resources(
        state,
        index,
        [resource_id],
    )
    resource = rows.get(resource_id)
    if resource is None:
        raise _resource_not_found()
    return resource


@router.post("/favorites/{resource_id}", status_code=201)
async def add_favorite(
    resource_id: str,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            await _require_visible_resource(
                state,
                index,
                resource_id,
            )
        await add_favorite_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
        )
        return {"ok": True, "favorited": True}


@router.delete("/favorites/{resource_id}")
async def remove_favorite(
    resource_id: str,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await remove_favorite_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
        )
        return {"ok": True, "favorited": False}


@router.get("/favorites/{resource_id}")
async def favorite_status(
    resource_id: str,
    request: Request,
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        return {
            "favorited": await favorite_record_exists(
                state,
                user_id=user.id,
                resource_id=resource_id,
            )
        }


@router.get("/favorites")
async def list_favorites(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        favorites = await list_favorite_records(
            state,
            user_id=user.id,
        )
        async with IndexSession() as index:
            by_id = await _visible_resources(
                state,
                index,
                [item.resource_id for item in favorites],
            )

    items: list[dict] = []
    unavailable = 0
    for item in favorites:
        resource = by_id.get(item.resource_id)
        if resource is None:
            unavailable += 1
            continue
        items.append(
            {
                **_resource_summary(resource),
                "favorited_at": item.created_at,
            }
        )

    start = (max(1, page) - 1) * max(1, page_size)
    return {
        "items": items[
            start : start + max(1, page_size)
        ],
        "total": len(items),
        "unavailable_count": unavailable,
    }


@router.post("/history/{resource_id}/touch", status_code=204)
async def touch_history(
    resource_id: str,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            await _require_visible_resource(
                state,
                index,
                resource_id,
            )
        await touch_history_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
        )
    return None


@router.get("/history")
async def list_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        rows = await list_history_records(
            state,
            user_id=user.id,
        )
        async with IndexSession() as index:
            by_id = await _visible_resources(
                state,
                index,
                [item.resource_id for item in rows],
            )

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
    return {
        "items": items[
            start : start + max(1, page_size)
        ],
        "total": len(items),
        "unavailable_count": unavailable,
    }


@router.delete("/history/{resource_id}")
async def remove_history(
    resource_id: str,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await remove_history_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
        )
        return {"ok": True}


@router.delete("/history")
async def clear_history(request: Request):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await clear_history_records(
            state,
            user_id=user.id,
        )
        return {"ok": True}


@router.get("/playback/{resource_id}")
async def get_playback(
    resource_id: str,
    request: Request,
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            await _require_visible_resource(
                state,
                index,
                resource_id,
            )
        row = await get_playback_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
        )
        if row is None:
            return {
                "position_seconds": 0,
                "duration_seconds": 0,
                "completed": False,
            }
        return {
            "position_seconds": row.position_seconds,
            "duration_seconds": row.duration_seconds,
            "completed": row.completed,
            "last_played_at": row.last_played_at,
        }


@router.put("/playback/{resource_id}")
async def save_playback(
    resource_id: str,
    payload: PlaybackProgressInput,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        async with IndexSession() as index:
            await _require_visible_resource(
                state,
                index,
                resource_id,
            )
        result = await save_playback_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
            position_seconds=payload.position_seconds,
            duration_seconds=payload.duration_seconds,
        )
        return {
            "ok": True,
            "saved": result["saved"],
            **(
                {"completed": result["completed"]}
                if result["saved"]
                else {}
            ),
        }


@router.delete("/playback/{resource_id}")
async def reset_playback(
    resource_id: str,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        await reset_playback_record(
            state,
            user_id=user.id,
            resource_id=resource_id,
        )
        return {"ok": True}


@router.get("/playback")
async def list_playback(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
):
    async with StateSession() as state:
        _, user = await require_user(state, request)
        rows = await list_incomplete_playback_records(
            state,
            user_id=user.id,
        )
        async with IndexSession() as index:
            by_id = await _visible_resources(
                state,
                index,
                [item.resource_id for item in rows],
            )

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
                "position_seconds": item.position_seconds,
                "duration_seconds": item.duration_seconds,
                "last_played_at": item.last_played_at,
            }
        )

    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": len(items),
        "unavailable_count": unavailable,
    }
