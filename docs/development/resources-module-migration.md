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

R3 is split to avoid importing legacy Shares publication-scope logic into
Resources.

### R3a — list queries

Status: implemented in this change.

The `GET /api/resources` and `GET /api/folders` SQLAlchemy queries now live
behind Resources-owned domain views, application query ports, and a SQLAlchemy
query repository. The legacy router still resolves the enabled publication root
IDs and injects that scope into Resources, so Resources does not depend on
Shares internals.

Preserved behavior:

- resource type/content-type aliases;
- folder/parent aliases;
- sort keys and order validation;
- pagination and total pages;
- active-only filtering;
- enabled-root publication scope;
- root-vs-child folder filtering semantics;
- public DTOs do not expose storage paths.

### R3b — detail query boundary

Status: implemented in this change.

`GET /api/resources/{resource_id}` and `GET /api/folders/{folder_id}` now
delegate all SQLAlchemy query construction to the Resources query repository.

The router still resolves enabled publication root IDs and injects them into the
query service. Resources therefore does not import `shares.service`. This keeps
publication scope composition at the HTTP boundary until Providers exposes an
explicit enabled-root contract.

Preserved behavior includes:

- resource not-found vs publication-scope error mapping;
- parent breadcrumbs;
- related resource limit and modified-time ordering;
- previous/next sibling ordering within the same content root;
- folder breadcrumbs including the current folder;
- active-only child resources;
- folder child ordering;
- folder resource sort/pagination behavior.

This slice removes the `routers/resources.py -> sqlalchemy` debt ID and
ratchets the architecture baseline from 87 to 86.

### R3c — browse aggregation and legacy serializer cleanup

Move resource-facing parts of `routers/browse.py` and retire
`services/resources.py` once all callers use module-owned views.

## R4 — Preview and delivery separation

### R4a — preview lookup boundary

Status: implemented in this change.

The resource preview capability, text preview, PDF preview, and Office preview
routes no longer load `Resource` ORM directly. They request an internal
`ResourcePreviewView` from the Resources query boundary.

The preview DTO deliberately includes internal `path` and `root_mapping_id`
because legacy preview/cache/provider helpers require them, but it has no public
serializer and is never returned directly by an API endpoint.

The router still owns HTTP error mapping and enabled-root scope injection.
Existing `preview.py`, `office.py`, and connection-resolution behavior is
reused unchanged.

This removes the remaining `routers/resources.py -> cloudsite.models` debt ID
and ratchets architecture debt from 86 to 85. The Resources router is now
completely ORM-free.

### R4b — preview/provider composition

Status: implemented in this change.

Resources now owns a `ResourcePreviewService` plus preview-cache primitives.
The service depends on Providers only through
`modules/providers/contracts/public.py`.

The resources router no longer coordinates:

- `services.connections.resolve_resource_connection`;
- `load_text_preview`;
- `ensure_preview_cached`;
- `office_cache_filename`;
- preview ticket construction.

Provider credentials and AList client construction stay inside Providers.
Resources receives only a source URL when a cache miss requires upstream access.

The previous cache-first behavior is preserved: a fresh local preview cache is
served without contacting the provider, so a temporary provider outage does not
break already-cached text/PDF/Office previews.

No architecture-debt count changes in this slice; it removes orchestration debt
without introducing a new legacy import.

Delivery continues to own redirect preparation plus download event/diagnostic
tracking. Providers owns storage backend access and credentials.

## R5 — Legacy cleanup

After runtime consumers use Resources contracts, remove compatibility re-exports
and legacy resource-facing helpers. Resources should become active only when the
production path is module-owned and legacy dependency count reaches zero.

## Invariants

Every slice preserves stable IDs, database compatibility, visibility behavior,
pagination/sort behavior, preview/download endpoint compatibility, caller
transaction boundaries, and zero new architecture-debt IDs.
