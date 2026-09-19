# Indexing Module

## Responsibility

Inventory scan, resource inspection, and snapshot reconciliation. This module
replaces the legacy rolling sync with a task-driven, snapshot-based pipeline.
It walks a provider's content tree, produces resource skeletons, inspects each
for detail, and reconciles the result against the database in one atomic
snapshot commit.

Core duties:
- Scan a content root category and emit resource skeletons.
- Inspect a single resource for full detail (size, mime, hash).
- Reconcile a snapshot against current DB state (insert/update/delete).
- Drive scan orchestration via platform/tasks (lease, retry, resume).
- Record change records for downstream consumers (search, catalog).

## Public API

- `scan_category(content_root, category)` - enqueue a scan task.
- `inspect_resource(resource_id)` - enqueue an inspection task.
- `reconcile_snapshot(snapshot_id)` - commit snapshot to DB.
- `get_scan_status(task_id)` - query scan progress.
- `list_changes(since)` - feed change records to consumers.

Exports live in `contracts/public.py`. The `public/` directory holds stable
task payload schemas.

## Domain Model

- InventorySnapshot (id, content_root, started_at, committed_at, status)
- ResourceSkeleton (resource_id, path, size, mtime, provider_id)
- InspectionResult (resource_id, mime_type, checksum, preview_hint)
- ChangeRecord (resource_id, change_kind, before, after, snapshot_id)
- IndexingTask (id, kind, payload, lease_owner, status, retry_count)

## Database Tables

- `indexing_tasks` - scan and inspection task records (new).
- `inventory_snapshots` - snapshot metadata (new).
- `resource_skeletons` - lightweight scan results (new).
- Legacy tables `sync_runs`, `sync_root_results`, `sync_changes`,
  `sync_cycles`, `sync_cycle_items`, `folder_scan_state` are frozen and will
  be deleted in Phase 4 after full migration.

## Dependencies

- platform/db
- platform/tasks (task queue, lease, retry, worker runtime)
- modules/providers (via contracts) - to list and inspect provider objects.
- modules/resources (via contracts) - to write reconciled resource rows.
- modules/identity (via contracts) - to assign stable IDs to new objects.

## Events/Tasks

- Enqueues `scan_category`, `inspect_resource`, `reconcile_snapshot` tasks.
- Emits `indexing.scan_completed`, `indexing.change_detected`.
- Consumers: search (re-index), catalog (metadata refresh), delivery (cache).
- Task lease and retry handled by platform/tasks, not this module.

## Security

- Scan tasks run with system scope, not user session; lease owner is a worker.
- Provider credentials accessed via providers contracts; never read directly.
- Snapshot reconciliation is atomic; partial snapshots are rolled back.
- Change records do not include file contents, only metadata.

## Failure Modes

- Provider unavailable mid-scan: task retries with lease; partial skeletons
  are discarded on retry, not committed.
- Snapshot reconciliation conflict: last-writer-wins with change record; the
  next scan corrects drift.
- Task lease expiry: platform/tasks re-queues; no duplicate commit because
  snapshot IDs are idempotent.
- Inspection timeout: resource marked inspection_pending; next scan retries.

## Tests

- `tests/unit/` - skeleton extraction, reconciliation diff logic.
- `tests/contract/` - task payload schema, public API stability.
- Target coverage: scan resume, snapshot idempotency, change record emission.

## Do Not

- Do not run scans inline in request handlers; always via tasks.
- Do not write directly to resources/identity tables; use their contracts.
- Do not reuse legacy `sync_*` tables; write to the new indexing tables.
- Do not block the worker on a single slow provider; use per-task timeouts.

## Current Migration Status

This is a NEW module. Legacy `sync/rolling.py` (54KB) is frozen: no new logic
goes there. All new indexing code goes to `modules/indexing/`. The module
skeleton with task payload schemas in `public/` is in place. Full replacement
of rolling sync is a Phase 2-4 milestone; until then both may coexist with
feature flags selecting the pipeline.

Resource persistence is now outside the Indexing ownership boundary: the production reconciliation adapter consumes `modules/resources/contracts` only, while top-level task composition injects the Resources SQLAlchemy repository. Indexing no longer imports Folder/Resource ORM classes.

## I1 Shared-Core Debt Closure

The production AList adapter now uses a structural content-root protocol rather
than importing Provider ORM. The v2 production bridge uses `platform/db`
sessions and writes its progress payload without importing shared
`cloudsite.models`.

This removes all three tracked Indexing `module_legacy_import` debt IDs.

Indexing remains **active**, not yet **isolated**: the compatibility production
bridge still calls legacy `cloudsite.indexer.load_all_connections_and_roots`
and `log_operation`. Those orchestration helpers should move behind Providers
and observability contracts before the legacy bridge can be deleted.

## I2 Frozen Legacy Sync Ownership

The frozen 1.x sync tables (`sync_runs`, `sync_root_results`, `sync_changes`,
`sync_cycles`, `sync_cycle_items`, and `folder_scan_state`) are now declared
under `modules/indexing/infrastructure/legacy_models.py`. This is ownership of
compatibility state, not permission to add new rolling-sync behavior.

`cloudsite.models` keeps exact compatibility re-exports. Consumers that need
read-only legacy sync information use the Indexing public contract and receive
persistence-neutral run/change views instead of ORM rows.
