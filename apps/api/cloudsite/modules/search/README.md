# Search Module

## Responsibility

Full-text search, search projection, and search index recovery. This module
owns the FTS5 index over resources and catalog entries. It projects domain
data into a search-optimized shape and serves user queries with filtering,
sorting, and faceting. It also handles index rebuild and recovery when the
FTS index is corrupted or out of sync.

Core duties:
- Execute full-text queries with filters and sort.
- Project resource and catalog data into the FTS index.
- Rebuild the index from authoritative DB state.
- Recover a corrupted FTS index without downtime.
- Log search queries for analytics and ranking tuning.

## Public API

- `search(query, filters, sort, page)` - full-text search with pagination.
- `rebuild_index()` - full FTS rebuild from DB (task-driven).
- `recover_index()` - detect and repair FTS corruption.
- `upsert_search_doc(resource_id)` - project one resource into FTS.
- `delete_search_doc(resource_id)` - remove from FTS on delete.

Exports live in `contracts/public.py`. The `public/` directory holds the
search document schema.

## Domain Model

- SearchQuery (text, filters, sort, page, facet)
- SearchResult (items, total, facets, took_ms)
- SearchProjection (resource_id, title, tags, mime_type, modified_at)
- SearchDoc (FTS row: resource_id, title, body, tags, metadata)

## Database Tables

- `fts_resources` - SQLite FTS5 virtual table (rebuilt, not migrated).
- `search_query_logs` - query analytics for ranking tuning.
- `catalog_search_outbox` - pending projection updates (outbox pattern).
- `catalog_search_projection_state` - projection watermark per source.

## Dependencies

- platform/db
- platform/tasks (for rebuild and recovery jobs)
- modules/resources (via contracts) - source data for projection.
- modules/catalog (via contracts) - catalog metadata for projection.

Search does not own the data; it owns the index over data owned by others.

## Events/Tasks

- Consumes `indexing.change_detected` to upsert/delete search docs.
- Consumes `catalog.metadata_changed` to refresh projection.
- Enqueues `rebuild_index` and `recover_index` as tasks.
- Emits `search.index_rebuilt` for operational monitoring.

## Security

- Search query text is parameterized; no raw SQL injection surface.
- Filters enforce visibility: a user only sees resources they can access.
- Query logs store the query text but not user PII beyond an opaque ID.
- Index rebuild runs with system scope; does not expose data via API.

## Failure Modes

- FTS index corrupted: recover_index detects and rebuilds; queries fail over
  to a degraded DB-side LIKE search until rebuild completes.
- Projection lag: outbox pattern ensures eventual consistency; stale results
  are acceptable for search, corrected on next projection tick.
- Rebuild OOM on large catalogs: rebuild is batched and resumable via tasks.
- Query timeout: return partial results with a `truncated` flag.

## Tests

- `tests/unit/` - query parsing, filter logic, projection mapping.
- `tests/contract/` - search doc schema, public API stability.
- Target coverage: search relevance, filter visibility, rebuild idempotency.

## Do Not

- Do not store authoritative data in the FTS index; it is rebuildable.
- Do not run rebuild inline; always via tasks.
- Do not bypass visibility filters; every query must scope to the user.
- Do not depend on modules/indexing directly; consume its events.

## Current Migration Status

Search is now **partial (S1)** rather than a skeleton.

S1 establishes the real public query/rebuild boundary:

- query normalization, match classification, filters and sort policy live in
  `domain/query.py`;
- SQLite FTS candidate matching and rebuild persistence live in
  `infrastructure/fts_repository.py`;
- public search orchestration lives in `application/service.py`;
- Resources supplies authoritative active/root-scoped search projections via
  its public contract instead of Search importing Folder/Resource ORM;
- `routers/search.py` and `routers/admin/search.py` no longer import ORM or
  SQLAlchemy;
- the legacy `cloudsite.search` module reuses the Search domain query policy
  so normalization/classification rules cannot drift.

S2a moves startup dirty-index recovery into the Search module. Dirty-state
inspection now uses Search-owned SQL, recovery composes platform DB sessions
with the Resources-backed rebuild path, and `cloudsite.search` keeps only a
compatibility export for the recovery symbol. Failed rebuilds still leave the
dirty marker set.

S2b verifies that the legacy row-level FTS delta path has no production caller:
v2 indexing refreshes public search through the module-owned rebuild contract,
and path mutation does not consume the delta helper. The orphaned
`FtsDeltaOp` / `apply_search_fts_delta` implementation and delta-only tests
are deleted instead of being mechanically moved into the module.

Still transitional after S2b:

- the Catalog search projection still lives behind the existing
  `services/catalog_search_projection.py` compatibility surface;
- rebuild remains synchronous for compatibility even though the target design
  is task-driven.
