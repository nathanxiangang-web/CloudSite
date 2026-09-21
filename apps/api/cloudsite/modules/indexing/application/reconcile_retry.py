"""Staging retry reconcile (V2 doc section 20).

After a failed reconcile, staging entries in ``index_scan_entries`` are
preserved.  This module retries reconcile directly from staging without
rescanning the provider root.

Flow::

    index_scan_entries (staging)
            |
            v
    load CategorySnapshot
            |
            v
    ReconcileService.reconcile
            |
            +-- success --> delete staging, commit
            |
            +-- failure --> rollback, staging preserved (retry again)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.snapshot import CategorySnapshot, SnapshotEntry
from ..infrastructure.repository import IndexingStore
from .reconcile import ReconcileResult, ReconcileService

logger = logging.getLogger(__name__)


async def _load_staging_snapshot(
    session: AsyncSession,
    run_id: str,
    category_id: str,
    provider_id: str,
) -> CategorySnapshot:
    """Build a :class:`CategorySnapshot` from ``index_scan_entries`` rows."""
    result = await session.execute(
        text(
            "SELECT resource_id, dir_path, path, parent_path, name, is_dir, "
            "size, modified, content_hash, metadata_json, metadata_hash "
            "FROM index_scan_entries WHERE scan_run_id = :rid ORDER BY id"
        ),
        {"rid": run_id},
    )
    entries: list[SnapshotEntry] = []
    for row in result:
        modified = row.modified
        if isinstance(modified, str):
            modified = datetime.fromisoformat(modified)

        metadata: dict[str, Any] = {}
        if row.metadata_json:
            try:
                decoded = json.loads(row.metadata_json)
                if isinstance(decoded, dict):
                    metadata.update(decoded)
            except (TypeError, ValueError):
                logger.warning(
                    "invalid staging metadata_json ignored (run_id=%s, resource_id=%s)",
                    run_id,
                    row.resource_id,
                )
        metadata["is_dir"] = bool(row.is_dir)
        if row.parent_path is not None:
            metadata["parent_path"] = row.parent_path

        entries.append(
            SnapshotEntry(
                resource_id=row.resource_id,
                path=row.path or row.dir_path,
                name=row.name,
                size=row.size,
                modified_at=modified,
                content_hash=row.content_hash or row.metadata_hash,
                metadata=metadata,
            )
        )
    return CategorySnapshot(
        category_id=category_id,
        provider_id=provider_id,
        entries=entries,
        pagination_complete=True,
    )


async def _delete_staging(session: AsyncSession, run_id: str) -> None:
    await session.execute(
        text("DELETE FROM index_scan_entries WHERE scan_run_id = :rid"),
        {"rid": run_id},
    )


async def retry_reconcile_from_staging(
    run_id: str,
    store: IndexingStore,
    *,
    category_id: str = "",
    provider_id: str = "",
) -> ReconcileResult:
    """Retry reconcile from staging without rescanning (V2 doc section 20).

    Loads the staging snapshot from ``index_scan_entries`` and reconciles
    directly.  On success the staging rows are deleted and the transaction
    is committed.  On failure the transaction is rolled back so staging is
    preserved and the caller can retry again.

    The ``store`` must expose its underlying session via a ``session``
    property or ``_session`` attribute so staging rows can be read and
    deleted.
    """
    session: AsyncSession | None = getattr(store, "session", None)
    if session is None:
        session = getattr(store, "_session", None)
    if session is None:
        raise ValueError("store must expose a session for staging access")

    snapshot = await _load_staging_snapshot(
        session, run_id, category_id, provider_id
    )

    reconcile_service = ReconcileService(store)
    try:
        result = await reconcile_service.reconcile(snapshot)
    except Exception:
        logger.exception(
            "retry reconcile from staging failed; "
            "staging preserved (run_id=%s)",
            run_id,
        )
        rollback = getattr(store, "rollback", None)
        if rollback is not None:
            await rollback()
        else:
            await session.rollback()
        raise

    await _delete_staging(session, run_id)
    commit = getattr(store, "commit", None)
    if commit is not None:
        await commit()
    else:
        await session.commit()
    return result


__all__ = ["retry_reconcile_from_staging"]
