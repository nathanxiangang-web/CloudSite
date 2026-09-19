# Resources Module Migration

Resources is a core CloudSite 2.0 boundary because Catalog, Search, Delivery,
Shares, and Indexing all reference Folder/Resource state.

## R1 — ORM ownership

Status: implemented in this change.

Resources now owns `DownloadRateLimit`, `Folder`, and `Resource` under
`modules/resources/infrastructure/models.py`.

`cloudsite.models` remains a compatibility re-export. No schema migration is
intended: table names, columns/defaults, constraints, and shared metadata stay
unchanged.

## R2 — Authoritative persistence port

Status: implemented in this change.

Folder/Resource reconciliation now crosses a Resources-owned public contract.

```text
Indexing
  -> modules/resources/contracts
      -> ResourceInventoryPort
          -> SqlAlchemyResourceInventoryRepository
              -> Folder / Resource ORM
```

Indexing's `ProductionIndexingStore` is now a persistence-neutral adapter over
`ResourceInventoryPort`; it imports neither SQLAlchemy nor `cloudsite.models`
nor Resources infrastructure internals. Top-level task composition wires the
adapter to `SqlAlchemyResourceInventoryRepository`, preserving the existing
caller-owned transaction and commit boundary.

Parent folder IDs are resolved while building the Indexing snapshot, before the
record crosses into Resources. Descendant path mutation is also Resources-owned;
the legacy Identity facade delegates to the Resources repository.

This slice removes one tracked `module_legacy_import` debt ID and ratchets the
architecture baseline from 88 to 87.

## R3 — Read/query boundary

Move browse/detail/folder queries behind Resources application services.
Legacy targets include `routers/resources.py`, resource-facing parts of
`routers/browse.py`, and `services/resources.py`.

## R4 — Preview and delivery separation

Resources owns resource metadata and preview preparation. Delivery owns redirect
preparation plus download event/diagnostic tracking. Providers owns storage
backend access and credentials.

## R5 — Legacy cleanup

After runtime consumers use Resources contracts, remove compatibility re-exports
and legacy resource-facing helpers. Resources should become active only when the
production path is module-owned and legacy dependency count reaches zero.

## Invariants

Every slice preserves stable IDs, database compatibility, visibility behavior,
pagination/sort behavior, preview/download endpoint compatibility, caller
transaction boundaries, and zero new architecture-debt IDs.
