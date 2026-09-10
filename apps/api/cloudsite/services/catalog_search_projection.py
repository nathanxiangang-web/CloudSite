"""D1 Catalog 搜索投影：ProjectionOutbox 消费者与 FTS 投影构建。

数据流：
- 业务写操作（services/catalog.py、catalog_metadata.py）在同一 state 事务内调用
  ``enqueue_catalog_search_outbox`` 追加一行 outbox，随业务一起 commit。
- 读路径（routers/catalog.py 的 /api/catalog/search）在查询前调用
  ``consume_catalog_search_outbox`` 同步消费所有 pending 行：
    1. 取 consumed_at IS NULL 的行，按 created_at 升序。
    2. 对每行：从 state.db 读 entry 当前 revision。
       - 若 entry 已不存在且 action=delete：从 index.db 删 FTS 行。
       - 若 entry.revision > outbox.revision：旧 revision 不覆盖新数据，仅标记 consumed。
       - 若 entry.revision == outbox.revision：
         * action=upsert：构建投影文档写入 catalog_search_fts（先删后插，幂等）。
         * action=delete：从 catalog_search_fts 删除。
    3. 在同一 index 事务内更新 catalog_search_projection_state.applied_revision。
    4. commit index 事务后，回写 state.db outbox.consumed_at 并 commit。
- 崩溃重放幂等：consumed_at IS NULL 的行重放；applied_revision >= outbox.revision
  的行直接跳过（水位保护）。
- 全量重建：``rebuild_catalog_search_index`` 清空 catalog_search_fts 与水位表，
  为所有 published entry 入 upsert outbox 行（由消费者统一投影，复用幂等路径）。

投影文档字段：
- title: entry.title
- summary: entry.summary
- description: entry.description
- aliases: entry.slug + 各 release.slug/title + 各 asset.slug/display_name（别名匹配）
- tags: 各 tag.slug + display_name
- platforms: 各 asset.platform/architecture/package_type + release.channel（允许展示的版本/平台）
- content_type: entry.content_type（UNINDEXED，用于过滤）

注意：投影仅含"已发布"语义的字段快照，但读时仍通过 catalog_entry_view fail-closed
实时校验 availability，权限过滤不依赖 FTS 删除。
"""
from __future__ import annotations

import re
import secrets
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogRelease,
    CatalogSearchOutbox,
    CatalogTag,
    CatalogTagAssignment,
    utcnow,
)

OUTBOX_ID_PREFIX = "cso_"
_ID_HEX_LEN = 32

_CATALOG_FTS_INSERT_SQL = text(
    "INSERT INTO catalog_search_fts(entry_id, content_type, title, summary, description, aliases, tags, platforms) "
    "VALUES (:entry_id, :content_type, :title, :summary, :description, :aliases, :tags, :platforms)"
)
_CATALOG_FTS_DELETE_SQL = text("DELETE FROM catalog_search_fts WHERE entry_id = :entry_id")
_PROJECTION_STATE_UPSERT_SQL = text(
    "INSERT INTO catalog_search_projection_state(entry_id, applied_revision, updated_at) "
    "VALUES (:entry_id, :applied_revision, :updated_at) "
    "ON CONFLICT(entry_id) DO UPDATE SET applied_revision = :applied_revision, updated_at = :updated_at"
)
_PROJECTION_STATE_GET_SQL = text(
    "SELECT applied_revision FROM catalog_search_projection_state WHERE entry_id = :entry_id"
)

_FTS_TOKEN_RE = re.compile(r"[0-9A-Za-z\u0080-\uffff]+")


def _new_outbox_id() -> str:
    return OUTBOX_ID_PREFIX + secrets.token_hex(_ID_HEX_LEN // 2)


def _build_fts_query(value: str) -> str:
    tokens = _FTS_TOKEN_RE.findall(value)[:8]
    return " AND ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens
    )


async def enqueue_catalog_search_outbox(
    state: AsyncSession,
    *,
    entry_id: str,
    revision: int,
    action: str = "upsert",
) -> None:
    """在同一 state 事务内追加一行投影 outbox。调用方负责 commit。

    幂等性：不在此处去重——消费者通过 revision 水位保证最终一致。多次入队
    只会产生多行 outbox，但每行消费时都会与 entry 当前 revision 比对，旧
    revision 行被跳过，因此重复入队不会破坏正确性。
    """
    if action not in {"upsert", "delete"}:
        raise ValueError(f"unsupported outbox action: {action}")
    state.add(
        CatalogSearchOutbox(
            outbox_id=_new_outbox_id(),
            entry_id=entry_id,
            revision=revision,
            action=action,
        )
    )
    await state.flush()


async def _build_projection_doc(state: AsyncSession, entry: CatalogEntry) -> dict[str, Any]:
    """从 state.db 实时组装 entry 的 FTS 投影文档。"""
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(CatalogRelease.entry_id == entry.entry_id)
            )
        ).all()
    )
    release_ids = [release.release_id for release in releases]
    assets = (
        list(
            (
                await state.scalars(
                    select(CatalogAsset).where(CatalogAsset.release_id.in_(release_ids))
                )
            ).all()
        )
        if release_ids
        else []
    )
    tag_rows = list(
        (
            await state.execute(
                select(CatalogTag.slug, CatalogTag.display_name)
                .join(CatalogTagAssignment, CatalogTagAssignment.tag_id == CatalogTag.tag_id)
                .where(
                    CatalogTagAssignment.target_type == "entry",
                    CatalogTagAssignment.target_id == entry.entry_id,
                )
            )
        ).all()
    )

    aliases_parts = [entry.slug]
    aliases_parts.extend(release.slug for release in releases)
    aliases_parts.extend(release.title for release in releases)
    aliases_parts.extend(asset.slug for asset in assets)
    aliases_parts.extend(asset.display_name for asset in assets)

    tags_parts: list[str] = []
    for slug, display_name in tag_rows:
        tags_parts.append(slug)
        tags_parts.append(display_name)

    platforms_parts: list[str] = []
    for release in releases:
        platforms_parts.append(release.channel or "unknown")
    for asset in assets:
        platforms_parts.append(asset.platform or "unknown")
        platforms_parts.append(asset.architecture or "unknown")
        platforms_parts.append(asset.package_type or "unknown")

    return {
        "entry_id": entry.entry_id,
        "content_type": entry.content_type,
        "title": entry.title,
        "summary": entry.summary or "",
        "description": entry.description or "",
        "aliases": " ".join(aliases_parts),
        "tags": " ".join(tags_parts),
        "platforms": " ".join(platforms_parts),
    }


async def _upsert_catalog_fts(index: AsyncSession, doc: dict[str, Any]) -> None:
    """先删后插，幂等。"""
    await index.execute(_CATALOG_FTS_DELETE_SQL, {"entry_id": doc["entry_id"]})
    await index.execute(_CATALOG_FTS_INSERT_SQL, doc)


async def _delete_catalog_fts(index: AsyncSession, entry_id: str) -> None:
    await index.execute(_CATALOG_FTS_DELETE_SQL, {"entry_id": entry_id})


async def _set_projection_state(
    index: AsyncSession, entry_id: str, applied_revision: int
) -> None:
    await index.execute(
        _PROJECTION_STATE_UPSERT_SQL,
        {
            "entry_id": entry_id,
            "applied_revision": applied_revision,
            "updated_at": utcnow(),
        },
    )


async def consume_catalog_search_outbox(
    state: AsyncSession,
    index: AsyncSession,
    *,
    batch_limit: int = 500,
) -> dict[str, int]:
    """同步消费所有 pending outbox 行。

    返回 {"consumed": N, "skipped": M, "failed": K}。读路径在搜索前调用，
    确保查询看到最新投影。消费者在 index 事务内推进水位，确认后回写 state。

    幂等保证：通过 catalog_search_projection_state.applied_revision 水位跳过
    已应用或更旧的行；通过 entry.revision vs outbox.revision 跳过被新写入
    覆盖的旧行。
    """
    pending = list(
        (
            await state.scalars(
                select(CatalogSearchOutbox)
                .where(CatalogSearchOutbox.consumed_at.is_(None))
                .order_by(CatalogSearchOutbox.created_at, CatalogSearchOutbox.outbox_id)
                .limit(batch_limit)
            )
        ).all()
    )
    if not pending:
        return {"consumed": 0, "skipped": 0, "failed": 0}

    consumed = 0
    skipped = 0
    failed = 0
    now = utcnow()

    for row in pending:
        try:
            existing_state = (
                await index.execute(_PROJECTION_STATE_GET_SQL, {"entry_id": row.entry_id})
            ).scalar_one_or_none()
            # 水位保护：已投影到 >= 此 revision 的行直接跳过（幂等重放）。
            if existing_state is not None and existing_state >= row.revision:
                skipped += 1
                row.consumed_at = now
                continue

            entry = await state.get(CatalogEntry, row.entry_id)
            # entry 已不存在或已非 published：从 FTS 删除（fail-closed）。
            if entry is None or entry.status != "published":
                await _delete_catalog_fts(index, row.entry_id)
                await _set_projection_state(index, row.entry_id, row.revision)
                consumed += 1
                row.consumed_at = now
                continue

            # 旧 revision 不覆盖新数据：entry 已推进到更高 revision，跳过本行。
            if entry.revision > row.revision:
                skipped += 1
                row.consumed_at = now
                continue

            if row.action == "delete":
                await _delete_catalog_fts(index, row.entry_id)
            else:
                doc = await _build_projection_doc(state, entry)
                await _upsert_catalog_fts(index, doc)
            await _set_projection_state(index, row.entry_id, row.revision)
            consumed += 1
            row.consumed_at = now
        except Exception:
            failed += 1
            # 单行失败不中断整体；下次读路径会重试。水位未推进故仍 pending。

    await index.commit()
    await state.commit()
    return {"consumed": consumed, "skipped": skipped, "failed": failed}


async def rebuild_catalog_search_index(
    state: AsyncSession,
    index: AsyncSession,
) -> int:
    """全量重建 catalog 搜索投影。

    清空 catalog_search_fts 与水位表，为所有 published entry 入 upsert outbox
    行，交由 consume_catalog_search_outbox 统一投影（复用幂等路径，确保重建
    后人工条目元数据仍可搜）。
    """
    await index.execute(text("DELETE FROM catalog_search_fts"))
    await index.execute(text("DELETE FROM catalog_search_projection_state"))
    await index.commit()

    entries = list(
        (
            await state.scalars(
                select(CatalogEntry).where(CatalogEntry.status == "published")
            )
        ).all()
    )
    # 清空旧 outbox pending 行，避免重复消费；新行由重建统一入队。
    pending_rows = list(
        (
            await state.scalars(
                select(CatalogSearchOutbox).where(CatalogSearchOutbox.consumed_at.is_(None))
            )
        ).all()
    )
    now = utcnow()
    for row in pending_rows:
        row.consumed_at = now
    for entry in entries:
        await enqueue_catalog_search_outbox(
            state, entry_id=entry.entry_id, revision=entry.revision, action="upsert"
        )
    await state.commit()

    stats = await consume_catalog_search_outbox(state, index)
    return stats["consumed"]


async def catalog_search_fts_match(
    index: AsyncSession,
    *,
    query: str,
    content_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """执行 catalog_search_fts MATCH，返回候选 entry 投影行。

    返回字段：entry_id, content_type, title。此处仅做 FTS 召回 + content_type
    过滤，权限/可用性过滤交给上层 catalog_entry_view fail-closed。
    """
    normalized = " ".join(query.strip().split())
    if not normalized:
        return []
    fts_query = _build_fts_query(normalized)
    if not fts_query:
        return []
    sql = text(
        "SELECT entry_id, content_type, title FROM catalog_search_fts "
        "WHERE catalog_search_fts MATCH :fts_query"
        + (" AND content_type = :content_type" if content_type else "")
        + " LIMIT :limit"
    )
    params: dict[str, Any] = {"fts_query": fts_query, "limit": limit}
    if content_type:
        params["content_type"] = content_type
    rows = (await index.execute(sql, params)).all()
    return [
        {"entry_id": row[0], "content_type": row[1], "title": row[2]}
        for row in rows
    ]
