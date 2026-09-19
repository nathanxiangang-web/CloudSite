"""Users-owned favorites, history and playback persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import (
    UserFavorite,
    UserPlaybackProgress,
    UserResourceHistory,
    utcnow,
)


HISTORY_TOUCH_INTERVAL_SECONDS = 300
HISTORY_MAX_PER_USER = 500
PROGRESS_MIN_POSITION_SECONDS = 5
COMPLETED_RATIO = 0.90
COMPLETED_REMAINING_SECONDS = 30


@dataclass(frozen=True, slots=True)
class FavoriteRecord:
    resource_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    resource_id: str
    first_viewed_at: datetime
    last_viewed_at: datetime
    view_count: int


@dataclass(frozen=True, slots=True)
class PlaybackRecord:
    resource_id: str
    position_seconds: int
    duration_seconds: int
    completed: bool
    last_played_at: datetime


def compute_playback_completed(
    position: int,
    duration: int,
) -> bool:
    if duration <= 0:
        return False
    remaining_threshold = min(
        COMPLETED_REMAINING_SECONDS,
        duration * (1 - COMPLETED_RATIO),
    )
    return (
        position / duration >= COMPLETED_RATIO
        or (duration - position) <= remaining_threshold
    )


async def add_favorite_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
) -> None:
    existing = await state.scalar(
        select(UserFavorite.id).where(
            UserFavorite.user_id == user_id,
            UserFavorite.resource_id == resource_id,
        )
    )
    if existing is not None:
        return
    state.add(
        UserFavorite(
            user_id=user_id,
            resource_id=resource_id,
        )
    )
    try:
        await state.commit()
    except IntegrityError:
        await state.rollback()


async def remove_favorite_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
) -> None:
    await state.execute(
        delete(UserFavorite).where(
            UserFavorite.user_id == user_id,
            UserFavorite.resource_id == resource_id,
        )
    )
    await state.commit()


async def favorite_record_exists(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
) -> bool:
    row_id = await state.scalar(
        select(UserFavorite.id).where(
            UserFavorite.user_id == user_id,
            UserFavorite.resource_id == resource_id,
        )
    )
    return row_id is not None


async def list_favorite_records(
    state: AsyncSession,
    *,
    user_id: int,
) -> list[FavoriteRecord]:
    rows = list(
        (
            await state.scalars(
                select(UserFavorite)
                .where(UserFavorite.user_id == user_id)
                .order_by(
                    UserFavorite.created_at.desc(),
                    UserFavorite.id.desc(),
                )
            )
        ).all()
    )
    return [
        FavoriteRecord(
            resource_id=row.resource_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _prune_history(
    state: AsyncSession,
    *,
    user_id: int,
) -> None:
    count = int(
        await state.scalar(
            select(func.count())
            .select_from(UserResourceHistory)
            .where(UserResourceHistory.user_id == user_id)
        )
        or 0
    )
    if count <= HISTORY_MAX_PER_USER:
        return

    oldest_ids = list(
        (
            await state.scalars(
                select(UserResourceHistory.id)
                .where(UserResourceHistory.user_id == user_id)
                .order_by(
                    UserResourceHistory.last_viewed_at.asc(),
                    UserResourceHistory.id.asc(),
                )
                .limit(count - HISTORY_MAX_PER_USER)
            )
        ).all()
    )
    if oldest_ids:
        await state.execute(
            delete(UserResourceHistory).where(
                UserResourceHistory.id.in_(oldest_ids)
            )
        )


async def touch_history_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
    now: datetime | None = None,
) -> None:
    current = now or utcnow()
    row = await state.scalar(
        select(UserResourceHistory).where(
            UserResourceHistory.user_id == user_id,
            UserResourceHistory.resource_id == resource_id,
        )
    )
    if row is None:
        state.add(
            UserResourceHistory(
                user_id=user_id,
                resource_id=resource_id,
                view_count=1,
                first_viewed_at=current,
                last_viewed_at=current,
            )
        )
    else:
        previous = row.last_viewed_at or current
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        since_last = (current - previous).total_seconds()
        if since_last < HISTORY_TOUCH_INTERVAL_SECONDS:
            await state.commit()
            return
        row.last_viewed_at = current
        row.view_count = (row.view_count or 0) + 1
        row.updated_at = current

    await state.commit()
    await _prune_history(
        state,
        user_id=user_id,
    )
    await state.commit()


async def list_history_records(
    state: AsyncSession,
    *,
    user_id: int,
) -> list[HistoryRecord]:
    rows = list(
        (
            await state.scalars(
                select(UserResourceHistory)
                .where(UserResourceHistory.user_id == user_id)
                .order_by(
                    UserResourceHistory.last_viewed_at.desc(),
                    UserResourceHistory.id.desc(),
                )
            )
        ).all()
    )
    return [
        HistoryRecord(
            resource_id=row.resource_id,
            first_viewed_at=row.first_viewed_at,
            last_viewed_at=row.last_viewed_at,
            view_count=int(row.view_count or 0),
        )
        for row in rows
    ]


async def remove_history_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
) -> None:
    await state.execute(
        delete(UserResourceHistory).where(
            UserResourceHistory.user_id == user_id,
            UserResourceHistory.resource_id == resource_id,
        )
    )
    await state.commit()


async def clear_history_records(
    state: AsyncSession,
    *,
    user_id: int,
) -> None:
    await state.execute(
        delete(UserResourceHistory).where(
            UserResourceHistory.user_id == user_id
        )
    )
    await state.commit()


async def get_playback_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
) -> PlaybackRecord | None:
    row = await state.scalar(
        select(UserPlaybackProgress).where(
            UserPlaybackProgress.user_id == user_id,
            UserPlaybackProgress.resource_id == resource_id,
        )
    )
    if row is None:
        return None
    return PlaybackRecord(
        resource_id=row.resource_id,
        position_seconds=row.position_seconds,
        duration_seconds=row.duration_seconds,
        completed=bool(row.completed),
        last_played_at=row.last_played_at,
    )


async def save_playback_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
    position_seconds: int,
    duration_seconds: int,
    now: datetime | None = None,
) -> dict[str, bool]:
    current = now or utcnow()
    row = await state.scalar(
        select(UserPlaybackProgress).where(
            UserPlaybackProgress.user_id == user_id,
            UserPlaybackProgress.resource_id == resource_id,
        )
    )
    completed = compute_playback_completed(
        position_seconds,
        duration_seconds,
    )
    if row is None:
        if (
            position_seconds < PROGRESS_MIN_POSITION_SECONDS
            and not completed
        ):
            return {
                "saved": False,
                "completed": completed,
            }
        state.add(
            UserPlaybackProgress(
                user_id=user_id,
                resource_id=resource_id,
                position_seconds=position_seconds,
                duration_seconds=duration_seconds,
                completed=completed,
                last_played_at=current,
            )
        )
    else:
        row.position_seconds = position_seconds
        row.duration_seconds = duration_seconds
        row.completed = completed
        row.last_played_at = current
        row.updated_at = current

    try:
        await state.commit()
    except IntegrityError:
        await state.rollback()

    return {
        "saved": True,
        "completed": completed,
    }


async def reset_playback_record(
    state: AsyncSession,
    *,
    user_id: int,
    resource_id: str,
) -> None:
    await state.execute(
        delete(UserPlaybackProgress).where(
            UserPlaybackProgress.user_id == user_id,
            UserPlaybackProgress.resource_id == resource_id,
        )
    )
    await state.commit()


async def list_incomplete_playback_records(
    state: AsyncSession,
    *,
    user_id: int,
) -> list[PlaybackRecord]:
    rows = list(
        (
            await state.scalars(
                select(UserPlaybackProgress)
                .where(
                    UserPlaybackProgress.user_id == user_id,
                    UserPlaybackProgress.completed.is_(False),
                )
                .order_by(
                    UserPlaybackProgress.last_played_at.desc(),
                    UserPlaybackProgress.id.desc(),
                )
            )
        ).all()
    )
    return [
        PlaybackRecord(
            resource_id=row.resource_id,
            position_seconds=row.position_seconds,
            duration_seconds=row.duration_seconds,
            completed=bool(row.completed),
            last_played_at=row.last_played_at,
        )
        for row in rows
    ]


__all__ = [
    "COMPLETED_RATIO",
    "COMPLETED_REMAINING_SECONDS",
    "FavoriteRecord",
    "HISTORY_MAX_PER_USER",
    "HISTORY_TOUCH_INTERVAL_SECONDS",
    "HistoryRecord",
    "PROGRESS_MIN_POSITION_SECONDS",
    "PlaybackRecord",
    "add_favorite_record",
    "clear_history_records",
    "compute_playback_completed",
    "favorite_record_exists",
    "get_playback_record",
    "list_favorite_records",
    "list_history_records",
    "list_incomplete_playback_records",
    "remove_favorite_record",
    "remove_history_record",
    "reset_playback_record",
    "save_playback_record",
    "touch_history_record",
]
