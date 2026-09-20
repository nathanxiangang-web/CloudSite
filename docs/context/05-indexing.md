# AI Context Pack: Indexing

Purpose: explain the indexing pipeline so an AI agent can modify scan, inspect,
or reconcile logic correctly. Indexing replaces the legacy rolling sync.

## Why a New Pipeline

The legacy rolling sync (sync/rolling.py, 54KB) has problems:
- No snapshot boundary; partial scans commit incrementally, causing
  inconsistent intermediate states for search and catalog.
- No resume; an interrupted scan restarts from the beginning.
- No change feed; downstream consumers poll the DB to detect changes.
- Tightly coupled to provider list logic; hard to test or replace.

The new pipeline in modules/indexing/ is snapshot-based and task-driven.

## Pipeline Stages

```text
1. Scan (task: scan_category)
   Walk a content root category via providers contracts.
   Emit resource skeletons (path, size, mtime, provider_id).
   No DB writes during the walk; skeletons are staged.

2. Inspect (task: inspect_resource, per resource)
   Fetch full detail (mime_type, checksum, preview_hint) for skeletons
   that need it. Batched and parallelized via the task queue.

3. Reconcile (task: reconcile_snapshot)
   Compare the snapshot against current DB state in one atomic transaction.
   Produce change records: insert, update, delete.
   Commit the snapshot; downstream consumers read change records.

4. Change feed
   Change records are consumed by search and catalog via events, not polling.
   search.upsert_search_doc / search.delete_search_doc
   catalog.refresh_entry_link
```

## Snapshot Semantics

- A snapshot has a unique ID and covers one content root category.
- Reconcile is idempotent by snapshot ID: a retry does not double-commit.
- Reconcile is atomic: either the whole snapshot commits or it rolls back.
- Partial snapshots (scan interrupted) are discarded on retry, not committed.

## Delta vs Full Scan

- Delta scan: uses a cursor (mtime/path watermark from provider_sync_state)
  to list only changed objects since the last scan. Cheaper, used normally.
- Full scan: walks the entire tree. Used for periodic drift correction
  (unreliable provider mtime) and initial backfill.
- The providers module's capability model (ADR-005) determines whether delta
  is available. If not, indexing falls back to full scan for that provider.

## Task Integration

All three stages run as tasks on the platform/tasks queue (ADR-002):
- scan_category: one task per content root category.
- inspect_resource: one task per resource, batched.
- reconcile_snapshot: one task per snapshot, after scan+inspect complete.

This gives the pipeline lease (resume after worker death), retry (transient
provider failures), backpressure (bounded workers), and visibility (queue
status).

## Change Records

A change record captures:
- resource_id (stable, from identity module).
- change_kind: insert, update, delete.
- before: prior state (for update/delete).
- after: new state (for insert/update).
- snapshot_id: which snapshot produced this change.

Consumers:
- search: upsert or delete the search doc for the resource.
- catalog: refresh the entry-to-resource link if the resource moved or changed.
- delivery: invalidate cached redirect entries for deleted resources.

## Identity Integration

When a scan finds a new or changed object, it does not assign a resource ID
directly. It calls identity.contracts to:
- Compute a fingerprint (path + provider + size + mtime).
- Resolve or create a stable resource ID.
- Reconcile identity candidates if the fingerprint changed.

This keeps resource IDs stable across moves and renames, so shares,
favorites, and playback progress continue to resolve.

## Legacy Coexistence

- Legacy sync/rolling.py is frozen: no new logic goes there.
- New code goes to modules/indexing/.
- Both pipelines coexist under feature flags until the new one is proven.
- Legacy sync_* tables are frozen and deleted in Phase 4.
- New tables: indexing_tasks, inventory_snapshots, resource_skeletons.

## Failure Handling

- Provider unavailable mid-scan: task retries with lease; partial skeletons
  discarded on retry.
- Reconcile conflict: last-writer-wins with change record; next scan corrects.
- Lease expiry: platform/tasks re-queues; no duplicate commit (idempotent
  snapshot ID).
- Inspection timeout: resource marked inspection_pending; next scan retries.
- Delta cursor miss (provider mtime unreliable): periodic full scan corrects.

## Do Not

- Do not run scans inline in request handlers; always via tasks.
- Do not write directly to resources/identity tables; use their contracts.
- Do not reuse legacy sync_* tables; write to indexing_* tables.
- Do not block the worker on a slow provider; use per-task timeouts.
- Do not commit partial snapshots; reconcile is all-or-nothing.