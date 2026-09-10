"""C4 资源关注与更新通知应用层。

关注关系（CatalogFavorite）与文件级收藏（UserFavorite）严格分离：本模块
只处理 catalog_entries.entry_id 维度的关注与通知订阅。文件收藏/历史/播放
进度语义零改动。

事务归属归调用方：本模块只 flush，不 commit。路由层在请求事务内提交。

通知去重：发布 release 时按 (release_id, user_id) 唯一约束幂等插入
CatalogReleaseNotification，重复发布（publish→unpublish→publish）不重复
通知。普通索引核验/文件同步不触发本逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogEntry,
    CatalogFavorite,
    CatalogRelease,
    CatalogReleaseNotification,
    CatalogSubscription,
    Notification,
    utcnow,
)


class CatalogFollowError(Exception):
    """C4 关注应用层错误基类。"""


class CatalogEntryNotFollowable(CatalogFollowError):
    def __init__(self, entry_id: str, reason: str = "entry_not_found"):
        super().__init__(f"catalog entry not followable: {entry_id} ({reason})")
        self.entry_id = entry_id
        self.reason = reason


@dataclass
class FollowStatus:
    favorited: bool
    notify_enabled: bool


async def _ensure_published_entry(state: AsyncSession, entry_id: str) -> CatalogEntry:
    """仅允许关注已发布条目，避免通过关注关系泄漏未发布条目。"""
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None or entry.status != "published":
        raise CatalogEntryNotFollowable(entry_id)
    return entry


async def follow_entry(
    state: AsyncSession,
    *,
    user_id: int,
    entry_id: str,
) -> FollowStatus:
    """关注一个 catalog 条目，幂等。

    关注时同步确保存在 CatalogSubscription 行且 notify_enabled=True。
    重复关注不报错，仅把 notify_enabled 置回 True（重新订阅）。
    仅允许关注已发布条目。
    """
    await _ensure_published_entry(state, entry_id)

    existing = await state.scalar(
        select(CatalogFavorite).where(
            CatalogFavorite.user_id == user_id,
            CatalogFavorite.entry_id == entry_id,
        )
    )
    if existing is None:
        state.add(CatalogFavorite(user_id=user_id, entry_id=entry_id))
        try:
            await state.flush()
        except IntegrityError as exc:
            await state.rollback()
            raise CatalogEntryNotFollowable(entry_id, "conflict") from exc

    sub = await state.scalar(
        select(CatalogSubscription).where(
            CatalogSubscription.user_id == user_id,
            CatalogSubscription.entry_id == entry_id,
        )
    )
    if sub is None:
        state.add(
            CatalogSubscription(
                user_id=user_id, entry_id=entry_id, notify_enabled=True
            )
        )
    elif not sub.notify_enabled:
        sub.notify_enabled = True
        sub.updated_at = utcnow()
    await state.flush()
    return FollowStatus(favorited=True, notify_enabled=True)


async def unfollow_entry(
    state: AsyncSession,
    *,
    user_id: int,
    entry_id: str,
) -> FollowStatus:
    """取关一个 catalog 条目，幂等。

    删除 CatalogFavorite 与 CatalogSubscription 行。CatalogReleaseNotification
    去重记录保留，避免重新关注后对同一 release 重复通知。
    """
    await state.execute(
        delete(CatalogFavorite).where(
            CatalogFavorite.user_id == user_id,
            CatalogFavorite.entry_id == entry_id,
        )
    )
    await state.execute(
        delete(CatalogSubscription).where(
            CatalogSubscription.user_id == user_id,
            CatalogSubscription.entry_id == entry_id,
        )
    )
    await state.flush()
    return FollowStatus(favorited=False, notify_enabled=False)


async def get_follow_status(
    state: AsyncSession,
    *,
    user_id: int,
    entry_id: str,
) -> FollowStatus:
    """查询当前用户对某条目的关注与通知订阅状态。"""
    fav = await state.scalar(
        select(CatalogFavorite.id).where(
            CatalogFavorite.user_id == user_id,
            CatalogFavorite.entry_id == entry_id,
        )
    )
    if fav is None:
        return FollowStatus(favorited=False, notify_enabled=False)
    sub = await state.scalar(
        select(CatalogSubscription.notify_enabled).where(
            CatalogSubscription.user_id == user_id,
            CatalogSubscription.entry_id == entry_id,
        )
    )
    return FollowStatus(favorited=True, notify_enabled=bool(sub))


async def set_subscription_notify(
    state: AsyncSession,
    *,
    user_id: int,
    entry_id: str,
    notify_enabled: bool,
) -> FollowStatus:
    """更新通知订阅开关（退订/重新订阅）。

    要求当前已关注该条目；未关注时返回未关注状态而非隐式创建订阅。
    """
    fav = await state.scalar(
        select(CatalogFavorite.id).where(
            CatalogFavorite.user_id == user_id,
            CatalogFavorite.entry_id == entry_id,
        )
    )
    if fav is None:
        return FollowStatus(favorited=False, notify_enabled=False)
    sub = await state.scalar(
        select(CatalogSubscription).where(
            CatalogSubscription.user_id == user_id,
            CatalogSubscription.entry_id == entry_id,
        )
    )
    if sub is None:
        state.add(
            CatalogSubscription(
                user_id=user_id,
                entry_id=entry_id,
                notify_enabled=notify_enabled,
            )
        )
    elif sub.notify_enabled != notify_enabled:
        sub.notify_enabled = notify_enabled
        sub.updated_at = utcnow()
    await state.flush()
    return FollowStatus(favorited=True, notify_enabled=notify_enabled)


def _latest_release_summary(releases: list[CatalogRelease]) -> dict | None:
    """从已发布 release 列表中取最新一条作为摘要。

    优先取 published_at 最新的；同 published_at 取 sort_order 最小。
    无已发布 release 时返回 None。
    """
    published = [r for r in releases if r.status == "published" and r.published_at is not None]
    if not published:
        return None
    latest = max(
        published,
        key=lambda r: (r.published_at, -r.sort_order),
    )
    return {
        "release_id": latest.release_id,
        "title": latest.title,
        "slug": latest.slug,
        "channel": latest.channel,
        "published_at": latest.published_at,
        "release_date": latest.release_date,
        "is_recommended": bool(latest.is_recommended),
    }


@dataclass
class FollowListResult:
    items: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


async def list_my_follows(
    state: AsyncSession,
    *,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> FollowListResult:
    """我的关注列表，分页，含条目最新发布版本摘要。

    仅返回当前仍为 published 的条目（按用户可见范围过滤，不泄漏已下架/草稿）。
    """
    total = int(
        await state.scalar(
            select(func.count())
            .select_from(CatalogFavorite)
            .join(CatalogEntry, CatalogEntry.entry_id == CatalogFavorite.entry_id)
            .where(
                CatalogFavorite.user_id == user_id,
                CatalogEntry.status == "published",
            )
        )
        or 0
    )
    page = max(int(page), 1)
    page_size = max(int(page_size), 1)
    offset = (page - 1) * page_size

    rows = list(
        (
            await state.scalars(
                select(CatalogFavorite)
                .join(CatalogEntry, CatalogEntry.entry_id == CatalogFavorite.entry_id)
                .where(
                    CatalogFavorite.user_id == user_id,
                    CatalogEntry.status == "published",
                )
                .order_by(CatalogFavorite.created_at.desc(), CatalogFavorite.id.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
    )

    items: list[dict] = []
    for fav in rows:
        entry = await state.get(CatalogEntry, fav.entry_id)
        if entry is None or entry.status != "published":
            continue
        sub = await state.scalar(
            select(CatalogSubscription.notify_enabled).where(
                CatalogSubscription.user_id == user_id,
                CatalogSubscription.entry_id == fav.entry_id,
            )
        )
        releases = list(
            (
                await state.scalars(
                    select(CatalogRelease).where(
                        CatalogRelease.entry_id == fav.entry_id
                    )
                )
            ).all()
        )
        items.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "slug": entry.slug,
                "content_type": entry.content_type,
                "summary": entry.summary,
                "favorited_at": fav.created_at,
                "notify_enabled": bool(sub),
                "latest_release": _latest_release_summary(releases),
            }
        )

    return FollowListResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


async def notify_release_subscribers(
    state: AsyncSession,
    *,
    release: CatalogRelease,
    entry: CatalogEntry,
) -> int:
    """发布新 release 时向关注者推送更新通知，返回实际通知人数。

    仅向 notify_enabled=True 的订阅者推送；按 (release_id, user_id) 去重，
    重复发布不重复通知。通知不泄漏未发布条目：调用方应仅在 release 与 entry
    均已 published 时调用。在请求事务内完成，不引入新基础设施。
    """
    if release.status != "published" or entry.status != "published":
        return 0

    subscribers = list(
        (
            await state.scalars(
                select(CatalogSubscription.user_id).where(
                    CatalogSubscription.entry_id == release.entry_id,
                    CatalogSubscription.notify_enabled.is_(True),
                )
            )
        ).all()
    )
    if not subscribers:
        return 0

    title = f"《{entry.title}》发布了新版本 {release.title}"
    body = release.release_notes or ""
    notified = 0
    for user_id in subscribers:
        existing = await state.scalar(
            select(CatalogReleaseNotification.id).where(
                CatalogReleaseNotification.release_id == release.release_id,
                CatalogReleaseNotification.user_id == user_id,
            )
        )
        if existing is not None:
            continue
        async with state.begin_nested():
            notification = Notification(
                user_id=user_id,
                title=title,
                body=body,
                level="info",
                source="catalog_release",
                enabled=True,
                published_at=utcnow(),
            )
            state.add(notification)
            await state.flush()
            dedup = CatalogReleaseNotification(
                release_id=release.release_id,
                user_id=user_id,
                notification_id=notification.id,
            )
            state.add(dedup)
            await state.flush()
        notified += 1
    return notified
