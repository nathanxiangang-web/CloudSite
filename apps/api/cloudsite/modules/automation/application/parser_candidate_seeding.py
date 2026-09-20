"""Seed durable A1 parser candidates from completed sync changes.

Bridges completed resource add/update SyncChange rows into the existing
durable parser-candidate queue without making sync success depend on parser
availability. Repeated seeding is idempotent through the existing exact
input fingerprint and parser version. Neither database session is committed
inside this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...indexing.contracts.public import legacy_sync_queries
from .parser_candidate_batch import enqueue_indexed_resource
from .parser_candidates import ParserCandidateError

_SEED_CHANGE_TYPES = frozenset({"added", "updated"})
_SEEDABLE_RUN_STATUSES = frozenset({"success", "partial"})
MAX_SEED_ITEMS = 500


@dataclass(frozen=True)
class ParserCandidateSeedResult:
    """Outcome of a bounded seeding call.

    Attributes:
        created: New parser candidate tasks created.
        existing: Changes that mapped to an existing identical candidate.
        skipped: Changes skipped (removed, folder, missing, or inactive).
        error: Changes that raised an isolated per-item error.
        last_change_id: Highest SyncChange.id processed (after_change_id if none).
        stopped_reason: "max_items" or "exhausted".
    """

    created: int
    existing: int
    skipped: int
    error: int
    last_change_id: int
    stopped_reason: str


async def seed_parser_candidates_from_sync_run(
    state: AsyncSession,
    index: AsyncSession,
    *,
    sync_run_id: int,
    max_items: int,
    after_change_id: int = 0,
) -> ParserCandidateSeedResult:
    """Enqueue bounded parser candidates from one sync run's resource changes.

    Reads SyncChange rows for sync_run_id with id > after_change_id in
    ascending id order, up to max_items rows. For each resource added/updated
    change whose Resource is active, enqueues a parser candidate through
    enqueue_indexed_resource. Removed, folder, missing, and inactive rows are
    counted as skipped. One malformed or stale change is recorded as error
    and does not block later changes. Neither database session is committed.
    """

    if not isinstance(sync_run_id, int) or isinstance(sync_run_id, bool) or sync_run_id <= 0:
        raise ParserCandidateError("sync_run_id must be a positive integer")
    if not isinstance(max_items, int) or isinstance(max_items, bool) or not 1 <= max_items <= MAX_SEED_ITEMS:
        raise ParserCandidateError(f"max_items must be between 1 and {MAX_SEED_ITEMS}")
    if not isinstance(after_change_id, int) or isinstance(after_change_id, bool) or after_change_id < 0:
        raise ParserCandidateError("after_change_id must be a non-negative integer")

    sync_reader = legacy_sync_queries(index)
    sync_run = await sync_reader.get_run(sync_run_id)
    if sync_run is None:
        raise ParserCandidateError("sync run not found")
    if sync_run.status not in _SEEDABLE_RUN_STATUSES:
        raise ParserCandidateError("sync run is not completed or partial")

    page = await sync_reader.list_changes(
        sync_run_id=sync_run_id,
        after_change_id=after_change_id,
        limit=max_items,
    )
    has_more = page.has_more
    process_rows = page.items

    created = 0
    existing = 0
    skipped = 0
    error = 0
    last_change_id = after_change_id

    for change in process_rows:
        last_change_id = change.id
        if change.object_type != "resource" or change.change_type not in _SEED_CHANGE_TYPES:
            skipped += 1
            continue
        try:
            async with state.begin_nested():
                _, was_created = await enqueue_indexed_resource(state, index, change.object_id)
        except ParserCandidateError as exc:
            if str(exc) == "indexed resource is unavailable or inactive":
                skipped += 1
            else:
                error += 1
            continue
        except Exception:
            error += 1
            continue
        if was_created:
            created += 1
        else:
            existing += 1

    stopped_reason = "max_items" if has_more else "exhausted"
    return ParserCandidateSeedResult(
        created=created,
        existing=existing,
        skipped=skipped,
        error=error,
        last_change_id=last_change_id,
        stopped_reason=stopped_reason,
    )
