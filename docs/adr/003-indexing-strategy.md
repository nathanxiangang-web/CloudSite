# ADR-003: Indexing Strategy

Date: 2026-09-17
Status: Accepted
Supersedes: none

## Context

The legacy indexing is a rolling sync (`sync/rolling.py`, 54KB) that
continuously walks provider trees and updates the DB. Problems:

- No snapshot boundary; partial scans commit incrementally, causing
  inconsistent intermediate states for search and catalog.
- No resume; a scan interrupted mid-tree restarts from the beginning.
- No change feed; downstream consumers (search, catalog) poll the DB to detect
  changes, causing lag and redundant work.
- Tightly coupled to provider list logic; hard to test or replace.

## Decision

Replace rolling sync with a snapshot-based, task-driven pipeline in
`modules/indexing/`:

1. **Scan** (task): walk a content root category, emit resource skeletons
   (lightweight: path, size, mtime). No DB writes during the walk.
2. **Inspect** (task per resource): fetch full detail (mime, checksum) for
   skeletons that need it. Batched and parallelized via the task queue.
3. **Reconcile** (task): compare the snapshot against current DB state in one
   atomic transaction. Produce change records (insert, update, delete).
4. **Change feed**: change records are consumed by search and catalog via
   events, not polling.

Snapshots are idempotent by snapshot ID; a retry does not double-commit. The
pipeline runs entirely on the task queue (ADR-002), so it inherits lease,
retry, and backpressure.

## Alternatives Considered

1. **Keep rolling sync, add snapshots on top** - rejected: rolling sync's
   incremental commit model is fundamentally incompatible with atomic
   snapshots; patching it would be more complex than replacing it.
2. **Event-sourced provider webhooks** - rejected: AList does not provide
   reliable change webhooks; we must poll. Webhooks could complement later.
3. **CDC / logical replication from AList's DB** - rejected: AList's storage is
   not a DB we control; it is a storage gateway. We cannot rely on its internals.
4. **Full re-scan every cycle** - rejected: too expensive for large catalogs.
   Delta scans using a cursor (mtime/path watermark) are used instead.

## Consequences

- Positive: atomic snapshots eliminate inconsistent intermediate states.
- Positive: change feed removes polling lag for search and catalog.
- Positive: task-driven pipeline is resumable, testable, and observable.
- Negative: snapshot reconciliation is a heavier transaction than incremental
  commits; large catalogs may hold locks longer. Mitigated by batching.
- Negative: delta cursor can miss changes if a provider's mtime is unreliable;
  periodic full reconciles correct drift.
- Neutral: legacy rolling sync stays frozen under a feature flag until the new
  pipeline is proven, then is deleted in Phase 4.

## References

- ADR-002 (task queue)
- modules/indexing/README.md
- docs/development/migration-strategy.md