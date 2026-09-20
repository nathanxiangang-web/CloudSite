"""A4 content quality and maintenance todo queue.

 Detects quality issues (missing descriptions, stale locations, old versions,
 suspected duplicates, no-result queries) and turns them into actionable
 QualityTodo items. Supports user ContentFeedback and admin processing
 (dismiss/resolve). Detection is budget-controlled and idempotent: the same
 (todo_type, target_type, target_id) with status='open' is not duplicated.

 Transaction ownership stays with the caller. Functions accept state/index
 AsyncSession and only flush; the caller commits or rolls back.
"""
from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    ContentFeedback,
    QualityDetectionRun,
    QualityTodo,
    Resource,
    SearchQueryLog,
    utcnow,
)

TODO_ID_PREFIX = "ct_"
RUN_ID_PREFIX = "dr_"
FEEDBACK_ID_PREFIX = "cf_"
_ID_HEX_LEN = 32

_TODO_TYPE_MISSING_DESCRIPTION = "missing_description"
_TODO_TYPE_STALE_LOCATION = "stale_location"
_TODO_TYPE_OLD_VERSION_REVIEW = "old_version_review"
_TODO_TYPE_SOURCE_CONFLICT = "source_conflict"
_TODO_TYPE_SUSPECTED_DUPLICATE = "suspected_duplicate"
_TODO_TYPE_NO_RESULT_QUERY = "no_result_query"

DEFAULT_BUDGET_MS = 5000
DEFAULT_REVIEW_AGE_DAYS = 180
DEFAULT_NO_RESULT_THRESHOLD = 3
DEFAULT_DUPLICATE_LIMIT = 50


class QualityError(Exception):
    """Quality service error base class."""


class QualityTodoNotFound(QualityError):
    def __init__(self, todo_id: str):
        super().__init__(f"quality todo not found: {todo_id}")
        self.todo_id = todo_id


class QualityTodoStateInvalid(QualityError):
    def __init__(self, todo_id: str, reason: str):
        super().__init__(f"quality todo {todo_id} state invalid: {reason}")
        self.todo_id = todo_id
        self.reason = reason


class ContentFeedbackNotFound(QualityError):
    def __init__(self, feedback_id: str):
        super().__init__(f"content feedback not found: {feedback_id}")
        self.feedback_id = feedback_id


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


def _encode_detail(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


def _decode_detail(raw: str) -> dict[str, Any]:
    if not raw or raw == "{}":
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _four_states(file_exists: bool, download_ready: bool, preview_ready: bool, content_reviewed: bool) -> dict[str, bool]:
    return {
        "file_exists": file_exists,
        "download_ready": download_ready,
        "preview_ready": preview_ready,
        "content_reviewed": content_reviewed,
    }


@dataclass
class DetectionResult:
    run_id: str
    items_found: int
    items_deduplicated: int
    actual_ms: int
    status: str
    breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class DetectionRunRecord:
    run_id: str
    started_at: datetime
    completed_at: datetime | None
    items_found: int
    items_deduplicated: int
    budget_ms: int
    actual_ms: int | None
    status: str
    breakdown: dict[str, Any]


@dataclass
class TodoSummary:
    todo_id: str
    todo_type: str
    target_type: str
    target_id: str
    severity: str
    title: str
    detail: dict[str, Any]
    status: str
    source: str
    detection_run_id: str | None
    dismissed_by: str
    dismissed_at: datetime | None
    dismiss_reason: str
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class FeedbackSummary:
    feedback_id: str
    user_id: int
    target_type: str
    target_id: str
    feedback_kind: str
    description: str
    status: str
    admin_note: str
    reviewed_by: str
    reviewed_at: datetime | None
    todo_id: str | None
    created_at: datetime
    updated_at: datetime


async def _upsert_todo(
    state: AsyncSession,
    *,
    todo_type: str,
    target_type: str,
    target_id: str,
    severity: str,
    title: str,
    detail: dict[str, Any],
    run_id: str,
) -> bool:
    """Insert a quality todo or update the existing open one. Returns True if new."""
    existing = await state.scalar(
        select(QualityTodo).where(
            QualityTodo.todo_type == todo_type,
            QualityTodo.target_type == target_type,
            QualityTodo.target_id == target_id,
            QualityTodo.status == "open",
        )
    )
    if existing is not None:
        existing.title = title
        existing.detail_json = _encode_detail(detail)
        existing.severity = severity
        existing.detection_run_id = run_id
        existing.updated_at = utcnow()
        await state.flush()
        return False

    todo = QualityTodo(
        todo_id=_new_id(TODO_ID_PREFIX),
        todo_type=todo_type,
        target_type=target_type,
        target_id=target_id,
        severity=severity,
        title=title,
        detail_json=_encode_detail(detail),
        status="open",
        source="auto_detection",
        detection_run_id=run_id,
    )
    state.add(todo)
    await state.flush()
    return True


async def detect_missing_descriptions(
    state: AsyncSession,
    *,
    run_id: str,
    limit: int = 100,
) -> tuple[int, int]:
    """Find published entries without summary and description."""
    entries = (await state.scalars(
        select(CatalogEntry).where(
            CatalogEntry.status == "published",
            CatalogEntry.summary == "",
            CatalogEntry.description == "",
        ).limit(limit)
    )).all()
    found = 0
    dedup = 0
    for entry in entries:
        detail = _four_states(True, True, True, True)
        detail["entry_id"] = entry.entry_id
        detail["title"] = entry.title
        is_new = await _upsert_todo(
            state,
            todo_type=_TODO_TYPE_MISSING_DESCRIPTION,
            target_type="entry",
            target_id=entry.entry_id,
            severity="medium",
            title=f"资源「{entry.title}」缺少简介和说明",
            detail=detail,
            run_id=run_id,
        )
        if is_new:
            found += 1
        else:
            dedup += 1
    return found, dedup


async def detect_stale_locations(
    state: AsyncSession,
    index: AsyncSession,
    *,
    run_id: str,
    limit: int = 100,
) -> tuple[int, int]:
    """Find locations pointing to unavailable or missing files."""
    locations = (await state.scalars(
        select(CatalogLocation).where(
            CatalogLocation.status == "active",
        ).limit(limit)
    )).all()
    found = 0
    dedup = 0
    for loc in locations:
        resource = await index.scalar(
            select(Resource).where(Resource.id == loc.resource_id)
        )
        file_exists = resource is not None and resource.status == "active"
        download_ready = file_exists and loc.status == "active"
        preview_ready = file_exists and resource is not None and resource.content_type in (
            "image", "video", "audio", "document", "text",
        )
        if file_exists and download_ready:
            continue
        asset = await state.scalar(
            select(CatalogAsset).where(CatalogAsset.asset_id == loc.asset_id)
        )
        detail = _four_states(file_exists, download_ready, preview_ready, True)
        detail["location_id"] = loc.location_id
        detail["asset_id"] = loc.asset_id
        detail["resource_id"] = loc.resource_id
        detail["resource_status"] = resource.status if resource else "not_found"
        severity = "high" if not file_exists else "medium"
        title = f"交付物位置失效（asset={loc.asset_id[:8]}…）"
        if asset:
            title = f"交付物「{asset.display_name}」位置失效"
        is_new = await _upsert_todo(
            state,
            todo_type=_TODO_TYPE_STALE_LOCATION,
            target_type="location",
            target_id=loc.location_id,
            severity=severity,
            title=title,
            detail=detail,
            run_id=run_id,
        )
        if is_new:
            found += 1
        else:
            dedup += 1
    return found, dedup


async def detect_old_versions_for_review(
    state: AsyncSession,
    *,
    run_id: str,
    age_days: int = DEFAULT_REVIEW_AGE_DAYS,
    limit: int = 50,
) -> tuple[int, int]:
    """Find published releases older than age_days that may need review."""
    cutoff = utcnow() - timedelta(days=age_days)
    releases = (await state.scalars(
        select(CatalogRelease).where(
            CatalogRelease.status == "published",
            CatalogRelease.release_date < cutoff,
        ).limit(limit)
    )).all()
    found = 0
    dedup = 0
    for release in releases:
        entry = await state.scalar(
            select(CatalogEntry).where(CatalogEntry.entry_id == release.entry_id)
        )
        detail = _four_states(True, True, True, True)
        detail["release_id"] = release.release_id
        detail["entry_id"] = release.entry_id
        detail["release_date"] = release.release_date.isoformat() if release.release_date else None
        detail["age_days"] = age_days
        entry_title = entry.title if entry else release.entry_id
        is_new = await _upsert_todo(
            state,
            todo_type=_TODO_TYPE_OLD_VERSION_REVIEW,
            target_type="release",
            target_id=release.release_id,
            severity="low",
            title=f"资源「{entry_title}」版本「{release.title}」已超过 {age_days} 天未复核",
            detail=detail,
            run_id=run_id,
        )
        if is_new:
            found += 1
        else:
            dedup += 1
    return found, dedup


async def detect_suspected_duplicates(
    state: AsyncSession,
    *,
    run_id: str,
    limit: int = DEFAULT_DUPLICATE_LIMIT,
) -> tuple[int, int]:
    """Find published entries with similar titles (case-insensitive)."""
    entries = (await state.scalars(
        select(CatalogEntry).where(
            CatalogEntry.status == "published",
        ).limit(limit * 3)
    )).all()
    by_title: dict[str, list[CatalogEntry]] = {}
    for entry in entries:
        key = entry.title.strip().casefold()
        if not key:
            continue
        by_title.setdefault(key, []).append(entry)
    found = 0
    dedup = 0
    for title_key, group in by_title.items():
        if len(group) < 2:
            continue
        for entry in group:
            siblings = [e.entry_id for e in group if e.entry_id != entry.entry_id]
            detail = _four_states(True, True, True, True)
            detail["entry_id"] = entry.entry_id
            detail["title"] = entry.title
            detail["duplicate_entry_ids"] = siblings
            is_new = await _upsert_todo(
                state,
                todo_type=_TODO_TYPE_SUSPECTED_DUPLICATE,
                target_type="entry",
                target_id=entry.entry_id,
                severity="medium",
                title=f"资源「{entry.title}」疑似重复（{len(siblings)} 个同名条目）",
                detail=detail,
                run_id=run_id,
            )
            if is_new:
                found += 1
            else:
                dedup += 1
            if found + dedup >= limit:
                return found, dedup
    return found, dedup


async def detect_no_result_queries(
    state: AsyncSession,
    *,
    run_id: str,
    threshold: int = DEFAULT_NO_RESULT_THRESHOLD,
    limit: int = 50,
) -> tuple[int, int]:
    """Aggregate search query logs for frequent no-result queries."""
    rows = (await state.execute(
        select(
            SearchQueryLog.query,
            func.count(SearchQueryLog.log_id).label("cnt"),
        ).where(
            SearchQueryLog.result_count == 0,
        ).group_by(SearchQueryLog.query).having(
            func.count(SearchQueryLog.log_id) >= threshold,
        ).order_by(func.count(SearchQueryLog.log_id).desc()).limit(limit)
    )).all()
    found = 0
    dedup = 0
    for row in rows:
        query_text = row.query
        count = int(row.cnt)
        detail = _four_states(True, True, True, True)
        detail["query"] = query_text
        detail["occurrence_count"] = count
        is_new = await _upsert_todo(
            state,
            todo_type=_TODO_TYPE_NO_RESULT_QUERY,
            target_type="query",
            target_id=query_text[:64],
            severity="low",
            title=f"搜索「{query_text[:40]}」无结果（{count} 次）",
            detail=detail,
            run_id=run_id,
        )
        if is_new:
            found += 1
        else:
            dedup += 1
    return found, dedup


async def run_quality_detection(
    state: AsyncSession,
    index: AsyncSession,
    *,
    budget_ms: int = DEFAULT_BUDGET_MS,
) -> DetectionResult:
    """Run all detectors within a time budget. Returns DetectionResult."""
    run = QualityDetectionRun(
        run_id=_new_id(RUN_ID_PREFIX),
        budget_ms=budget_ms,
        status="running",
    )
    state.add(run)
    await state.flush()
    run_id = run.run_id

    start = time.monotonic()
    total_found = 0
    total_dedup = 0
    breakdown: dict[str, int] = {}
    timed_out = False

    detectors = [
        (_TODO_TYPE_MISSING_DESCRIPTION, lambda: detect_missing_descriptions(state, run_id=run_id)),
        (_TODO_TYPE_STALE_LOCATION, lambda: detect_stale_locations(state, index, run_id=run_id)),
        (_TODO_TYPE_OLD_VERSION_REVIEW, lambda: detect_old_versions_for_review(state, run_id=run_id)),
        (_TODO_TYPE_SUSPECTED_DUPLICATE, lambda: detect_suspected_duplicates(state, run_id=run_id)),
        (_TODO_TYPE_NO_RESULT_QUERY, lambda: detect_no_result_queries(state, run_id=run_id)),
    ]

    for label, detector in detectors:
        elapsed = int((time.monotonic() - start) * 1000)
        if elapsed >= budget_ms:
            timed_out = True
            break
        try:
            found, dedup = await detector()
            total_found += found
            total_dedup += dedup
            breakdown[label] = found
        except Exception:
            breakdown[label] = -1

    actual_ms = int((time.monotonic() - start) * 1000)
    run.completed_at = utcnow()
    run.items_found = total_found
    run.items_deduplicated = total_dedup
    run.actual_ms = actual_ms
    run.status = "timeout" if timed_out else "completed"
    run.detail_json = _encode_detail(breakdown)
    run.updated_at = utcnow() if hasattr(run, "updated_at") else run.started_at
    await state.flush()

    return DetectionResult(
        run_id=run_id,
        items_found=total_found,
        items_deduplicated=total_dedup,
        actual_ms=actual_ms,
        status=run.status,
        breakdown=breakdown,
    )


async def list_detection_runs(
    state: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DetectionRunRecord], int]:
    """List quality detection runs without exposing ORM rows."""

    total = int(
        await state.scalar(
            select(func.count()).select_from(QualityDetectionRun)
        )
        or 0
    )
    offset = (page - 1) * page_size
    rows = list(
        (
            await state.scalars(
                select(QualityDetectionRun)
                .order_by(QualityDetectionRun.started_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
    )
    return (
        [
            DetectionRunRecord(
                run_id=row.run_id,
                started_at=row.started_at,
                completed_at=row.completed_at,
                items_found=row.items_found,
                items_deduplicated=row.items_deduplicated,
                budget_ms=row.budget_ms,
                actual_ms=row.actual_ms,
                status=row.status,
                breakdown=_decode_detail(row.detail_json),
            )
            for row in rows
        ],
        total,
    )


async def list_quality_todos(
    state: AsyncSession,
    *,
    todo_type: str | None = None,
    status: str | None = None,
    target_type: str | None = None,
    severity: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TodoSummary], int]:
    """List quality todos with optional filters. Returns (items, total)."""
    conditions = []
    if todo_type:
        conditions.append(QualityTodo.todo_type == todo_type)
    if status:
        conditions.append(QualityTodo.status == status)
    if target_type:
        conditions.append(QualityTodo.target_type == target_type)
    if severity:
        conditions.append(QualityTodo.severity == severity)

    base = select(QualityTodo)
    count_q = select(func.count()).select_from(QualityTodo)
    if conditions:
        from sqlalchemy import and_
        base = base.where(and_(*conditions))
        count_q = count_q.where(and_(*conditions))

    total = int(await state.scalar(count_q) or 0)
    offset = (page - 1) * page_size
    rows = (await state.scalars(
        base.order_by(QualityTodo.created_at.desc()).offset(offset).limit(page_size)
    )).all()
    items = [_todo_to_summary(r) for r in rows]
    return items, total


async def get_quality_todo(state: AsyncSession, todo_id: str) -> TodoSummary:
    row = await state.scalar(select(QualityTodo).where(QualityTodo.todo_id == todo_id))
    if row is None:
        raise QualityTodoNotFound(todo_id)
    return _todo_to_summary(row)


async def dismiss_quality_todo(
    state: AsyncSession,
    todo_id: str,
    *,
    dismissed_by: str = "admin",
    reason: str = "",
) -> TodoSummary:
    row = await state.scalar(select(QualityTodo).where(QualityTodo.todo_id == todo_id))
    if row is None:
        raise QualityTodoNotFound(todo_id)
    if row.status != "open":
        raise QualityTodoStateInvalid(todo_id, f"cannot dismiss todo with status '{row.status}'")
    row.status = "dismissed"
    row.dismissed_by = dismissed_by
    row.dismissed_at = utcnow()
    row.dismiss_reason = reason
    row.updated_at = utcnow()
    await state.flush()
    return _todo_to_summary(row)


async def resolve_quality_todo(
    state: AsyncSession,
    todo_id: str,
    *,
    resolved_by: str = "admin",
) -> TodoSummary:
    row = await state.scalar(select(QualityTodo).where(QualityTodo.todo_id == todo_id))
    if row is None:
        raise QualityTodoNotFound(todo_id)
    if row.status != "open":
        raise QualityTodoStateInvalid(todo_id, f"cannot resolve todo with status '{row.status}'")
    row.status = "resolved"
    row.resolved_at = utcnow()
    row.dismissed_by = resolved_by
    row.updated_at = utcnow()
    await state.flush()
    return _todo_to_summary(row)


@dataclass
class BatchDismissResult:
    results: list[tuple[str, bool, str]]
    succeeded: int
    failed: int


async def batch_dismiss_quality_todos(
    state: AsyncSession,
    todo_ids: list[str],
    *,
    dismissed_by: str = "admin",
    reason: str = "",
) -> BatchDismissResult:
    results: list[tuple[str, bool, str]] = []
    succeeded = 0
    failed = 0
    for tid in todo_ids:
        try:
            await dismiss_quality_todo(state, tid, dismissed_by=dismissed_by, reason=reason)
            results.append((tid, True, ""))
            succeeded += 1
        except QualityTodoNotFound:
            results.append((tid, False, "not_found"))
            failed += 1
        except QualityTodoStateInvalid as exc:
            results.append((tid, False, exc.reason))
            failed += 1
    return BatchDismissResult(results=results, succeeded=succeeded, failed=failed)


async def log_search_query(
    state: AsyncSession,
    *,
    query: str,
    result_count: int,
    user_id: int | None = None,
    content_type_filter: str | None = None,
    platform_filter: str | None = None,
) -> None:
    log = SearchQueryLog(
        query=query[:200],
        result_count=result_count,
        user_id=user_id,
        content_type_filter=content_type_filter,
        platform_filter=platform_filter,
    )
    state.add(log)
    await state.flush()


async def create_content_feedback(
    state: AsyncSession,
    *,
    user_id: int,
    target_type: str,
    target_id: str,
    feedback_kind: str,
    description: str,
) -> FeedbackSummary:
    todo_id = _new_id(TODO_ID_PREFIX)
    todo = QualityTodo(
        todo_id=todo_id,
        todo_type=_feedback_kind_to_todo_type(feedback_kind),
        target_type=target_type,
        target_id=target_id,
        severity="medium",
        title=f"用户反馈：{description[:80]}",
        detail_json=_encode_detail({
            "feedback_kind": feedback_kind,
            "description": description,
            "user_id": user_id,
            **_four_states(True, True, True, False),
        }),
        status="open",
        source="user_feedback",
    )
    state.add(todo)
    await state.flush()

    feedback = ContentFeedback(
        feedback_id=_new_id(FEEDBACK_ID_PREFIX),
        user_id=user_id,
        target_type=target_type,
        target_id=target_id,
        feedback_kind=feedback_kind,
        description=description[:1000],
        status="pending",
        todo_id=todo_id,
    )
    state.add(feedback)
    await state.flush()
    return _feedback_to_summary(feedback)


def _feedback_kind_to_todo_type(kind: str) -> str:
    mapping = {
        "broken_link": _TODO_TYPE_STALE_LOCATION,
        "wrong_info": _TODO_TYPE_SOURCE_CONFLICT,
        "missing_content": _TODO_TYPE_MISSING_DESCRIPTION,
        "other": _TODO_TYPE_SOURCE_CONFLICT,
    }
    return mapping.get(kind, _TODO_TYPE_SOURCE_CONFLICT)


async def list_content_feedback(
    state: AsyncSession,
    *,
    status: str | None = None,
    target_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FeedbackSummary], int]:
    conditions = []
    if status:
        conditions.append(ContentFeedback.status == status)
    if target_type:
        conditions.append(ContentFeedback.target_type == target_type)

    base = select(ContentFeedback)
    count_q = select(func.count()).select_from(ContentFeedback)
    if conditions:
        from sqlalchemy import and_
        base = base.where(and_(*conditions))
        count_q = count_q.where(and_(*conditions))

    total = int(await state.scalar(count_q) or 0)
    offset = (page - 1) * page_size
    rows = (await state.scalars(
        base.order_by(ContentFeedback.created_at.desc()).offset(offset).limit(page_size)
    )).all()
    items = [_feedback_to_summary(r) for r in rows]
    return items, total


async def review_content_feedback(
    state: AsyncSession,
    feedback_id: str,
    *,
    reviewed_by: str = "admin",
    admin_note: str = "",
    new_status: str = "reviewed",
) -> FeedbackSummary:
    row = await state.scalar(select(ContentFeedback).where(ContentFeedback.feedback_id == feedback_id))
    if row is None:
        raise ContentFeedbackNotFound(feedback_id)
    if row.status != "pending":
        raise QualityTodoStateInvalid(feedback_id, f"cannot review feedback with status '{row.status}'")
    row.status = new_status
    row.admin_note = admin_note
    row.reviewed_by = reviewed_by
    row.reviewed_at = utcnow()
    row.updated_at = utcnow()
    if row.todo_id:
        todo = await state.scalar(select(QualityTodo).where(QualityTodo.todo_id == row.todo_id))
        if todo and todo.status == "open":
            todo.status = "resolved" if new_status == "resolved" else "dismissed"
            todo.resolved_at = utcnow() if new_status == "resolved" else None
            todo.dismissed_at = utcnow() if new_status != "resolved" else None
            todo.dismissed_by = reviewed_by
            todo.updated_at = utcnow()
    await state.flush()
    return _feedback_to_summary(row)


def _todo_to_summary(row: QualityTodo) -> TodoSummary:
    return TodoSummary(
        todo_id=row.todo_id,
        todo_type=row.todo_type,
        target_type=row.target_type,
        target_id=row.target_id,
        severity=row.severity,
        title=row.title,
        detail=_decode_detail(row.detail_json),
        status=row.status,
        source=row.source,
        detection_run_id=row.detection_run_id,
        dismissed_by=row.dismissed_by,
        dismissed_at=row.dismissed_at,
        dismiss_reason=row.dismiss_reason,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _feedback_to_summary(row: ContentFeedback) -> FeedbackSummary:
    return FeedbackSummary(
        feedback_id=row.feedback_id,
        user_id=row.user_id,
        target_type=row.target_type,
        target_id=row.target_id,
        feedback_kind=row.feedback_kind,
        description=row.description,
        status=row.status,
        admin_note=row.admin_note,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        todo_id=row.todo_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )