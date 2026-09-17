"""CloudSite cloud download submission service.

Reusable helpers that wrap the 115driver adapter and persist per-user
CloudDownloadTask rows. Submitted URLs are never persisted or logged;
only the owning user, driver hash, lifecycle status, and a safe generic
display name are stored. The helpers accept an explicit user_id so a
future AI submission path can call them under the same identity boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.models import CloudDownloadTask, utcnow
from .cloud_download_driver import (
    AddOfflineResult,
    CloudDownloadError,
    OfflineTask,
    add_offline_task,
    list_offline_tasks,
)

# Per-user daily submission limit.
DAILY_SUBMISSION_LIMIT: int = 10

# Safe generic display name; never the raw URL.
DEFAULT_DISPLAY_NAME: str = "Cloud download task"

# Neutral status used when the driver hash is not found in the CLI list.
UNKNOWN_STATUS: str = "submitted"

# Initial status for a freshly submitted task.
INITIAL_STATUS: str = "submitted"

# How many recent tasks GET returns per user.
RECENT_LIMIT: int = 50


def _today_start(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


async def _count_today(state: AsyncSession, user_id: int, now: datetime) -> int:
    start = _today_start(now)
    result = await state.execute(
        select(func.count(CloudDownloadTask.id)).where(
            CloudDownloadTask.user_id == user_id,
            CloudDownloadTask.created_at >= start,
        )
    )
    return int(result.scalar() or 0)


def cloud_download_task_dict(
    row: CloudDownloadTask,
    *,
    cli_task: OfflineTask | None = None,
) -> dict[str, Any]:
    """Serialize a CloudDownloadTask for public API output.

    Never includes driver_hash, user_id, or any URL/credential data.
    When cli_task is provided, the CLI-derived name/status/percent are
    used; otherwise a neutral submitted status is reported.
    """
    if cli_task is not None:
        name = cli_task.name
        status = cli_task.status
        percent = cli_task.percent
    else:
        name = row.display_name or DEFAULT_DISPLAY_NAME
        status = row.status or UNKNOWN_STATUS
        percent = 0.0
    return {
        "id": row.id,
        "name": name,
        "status": status,
        "percent": float(percent),
        "created_at": row.created_at,
    }


def _sanitize_cli_error(exc: CloudDownloadError) -> HTTPException:
    """Map a CloudDownloadError to a stable HTTPException without leaking details."""
    code_map = {
        "CD-001": (400, "CD_URL_INVALID"),
        "CD-002": (503, "CD_CLI_UNAVAILABLE"),
        "CD-003": (504, "CD_CLI_TIMEOUT"),
        "CD-004": (502, "CD_CLI_FAILED"),
        "CD-005": (502, "CD_CLI_MALFORMED"),
        "CD-006": (502, "CD_CLI_DESTINATION_MISMATCH"),
    }
    status, code = code_map.get(exc.code, (502, "CD_CLI_ERROR"))
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": "Cloud download failed"},
    )


async def submit_cloud_download(
    state: AsyncSession,
    user_id: int,
    url: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Submit a URL for cloud download on behalf of a user.

    Validates the URL, enforces the per-user daily limit, calls the
    115driver adapter, persists a CloudDownloadTask with the driver hash
    and a safe display name, and returns the public task dict. The URL
    is never persisted or logged.
    """
    now = now or utcnow()
    today_count = await _count_today(state, user_id, now)
    if today_count >= DAILY_SUBMISSION_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"code": "CD_RATE_LIMIT", "message": "Daily cloud download limit reached"},
        )
    try:
        result: AddOfflineResult = await add_offline_task(url)
    except CloudDownloadError as exc:
        raise _sanitize_cli_error(exc) from exc
    driver_hash = result.hashes[0] if result.hashes else None
    row = CloudDownloadTask(
        user_id=user_id,
        driver_hash=driver_hash,
        status=INITIAL_STATUS,
        display_name=DEFAULT_DISPLAY_NAME,
        created_at=now,
        updated_at=now,
    )
    state.add(row)
    await state.flush()
    await state.refresh(row)
    return cloud_download_task_dict(row, cli_task=None)


async def list_user_cloud_download_tasks(
    state: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    """List the recent cloud download tasks for a user.

    Queries only this user's CloudDownloadTask rows (recent 50), reads
    the driver task list at most once, matches by driver_hash, and
    returns sanitized items. Never returns other account tasks or full
    URL/hash/credentials. If a submitted hash is not found in the CLI
    list, a neutral submitted status is kept; the task is not marked
    failed. CLI errors are sanitized into an empty match set.
    """
    rows = list(
        (
            await state.scalars(
                select(CloudDownloadTask)
                .where(CloudDownloadTask.user_id == user_id)
                .order_by(desc(CloudDownloadTask.created_at))
                .limit(RECENT_LIMIT)
            )
        ).all()
    )
    if not rows:
        return {"items": []}
    try:
        cli_tasks: list[OfflineTask] = await list_offline_tasks()
    except CloudDownloadError:
        cli_tasks = []
    cli_by_hash: dict[str, OfflineTask] = {task.hash: task for task in cli_tasks}
    items: list[dict[str, Any]] = []
    for row in rows:
        cli_task = cli_by_hash.get(row.driver_hash) if row.driver_hash else None
        items.append(cloud_download_task_dict(row, cli_task=cli_task))
    return {"items": items}
