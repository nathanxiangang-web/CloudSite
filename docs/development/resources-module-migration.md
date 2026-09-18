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

Move Folder/Resource mutation behind Resources-owned application ports.

```text
Indexing
  -> modules/resources/contracts
      -> Resources mutation service
          -> Resources repository
              -> Folder / Resource ORM
```

At the end of R2, Indexing no longer imports `cloudsite.models.Folder/Resource`
and does not import Resources infrastructure internals.

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
