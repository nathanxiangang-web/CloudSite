# Indexing Module Migration

Indexing owns scan/reconcile orchestration. Providers owns storage connections
and provider access; Resources owns authoritative Folder/Resource persistence.

## I1 — tracked shared-core debt closure

Status: implemented.

Three remaining tracked dependencies are removed:

- `alist_adapter.py -> cloudsite.models`
- `legacy_bridge.py -> cloudsite.database`
- `legacy_bridge.py -> cloudsite.models`

The AList adapter now accepts a structural `ContentRootView` protocol, so
Provider ORM may satisfy the shape without becoming an Indexing dependency.

The production bridge uses `platform/db.index_session()` /
`state_session()`. V2 progress continues to persist under the same
`system_settings.v2_sync_progress` key using a parameterized upsert.

The startup compatibility task also now calls the zero-argument production
composition entry correctly; it no longer passes an internal `store_factory`
argument to the wrapper.

Architecture debt ratchets from 79 to 76.

## I2 — production-loader isolation

Next, replace the remaining compatibility calls to:

- `cloudsite.indexer.load_all_connections_and_roots`
- `cloudsite.indexer.log_operation`

with Providers/observability boundaries.

Only after I2 should Indexing be described as isolated. The legacy rolling-sync
implementation remains frozen until the feature-flag fallback can be removed.

## Invariants

- scan/reconcile output is unchanged;
- per-category error isolation is unchanged;
- Resources still owns Folder/Resource writes;
- caller-owned IndexSession commit semantics are unchanged;
- v2 progress JSON/key semantics are unchanged;
- no new architecture debt IDs.
