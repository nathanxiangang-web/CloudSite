# Resources Module Migration

> **Historical execution record.** This document preserves the slice-by-slice migration plan and invariants at the time it was written. It is not the current backlog. Before acting on any `Next`, `Then`, or `Later` item here, check `module.yaml`, the module `README.md`, [modularization-status.md](./modularization-status.md), and issue #157 against current `main`.


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

### R4b — provider runtime preview composition

Status: implemented in this change.

Preview and Office cache helpers now consume the Providers public
`ProviderRuntimePort` instead of connection ORM objects. Credential
decryption, AList client construction, root-to-connection resolution, and
provider selection remain inside Providers.

The following preview paths now receive `provider_runtime(state)`:

- text preview;
- PDF/Office cache preparation;
- direct `/p/{resource_id}` redirect resolution.

`routers/previews.py` now loads resource visibility through the Resources query
boundary and no longer imports shared Resource ORM or calls
`resource_in_publication_scope()` directly.

The legacy `cloudsite.preview` and `cloudsite.office` modules remain temporary
compatibility facades, but CI forbids them from importing `AListClient` or
`decrypt_secret`.

This removes the `routers/previews.py -> cloudsite.models` debt ID and ratchets
architecture debt from 84 to 83.

### R4c — preview helper ownership cleanup

Status: implemented in this change.

The remaining implementation in top-level `cloudsite.preview` and
`cloudsite.office` now lives under Resources:

- `modules/resources/infrastructure/preview.py`;
- `modules/resources/infrastructure/office_preview.py`.

The top-level modules remain compatibility-only re-export facades so existing
imports keep exact class/function/cache/settings object identity.

CI enforces that:

- the top-level facades contain no function/class implementation;
- provider credentials and AList clients do not return to Resources preview
  helpers;
- preview/provider access continues through `modules/providers/contracts`.

This slice intentionally does not change the debt count: top-level
`preview.py` / `office.py` were legacy ownership debt but not one of the
ratchet's tracked ORM/shared-core IDs. The important change is that there is now
one authoritative implementation path.

### R4d — download/provider runtime composition

Status: implemented in this change.

The public download route now resolves a persistence-neutral
`ResourceDownloadView` through Resources. Missing, inactive, and
out-of-publication-scope resources remain distinct so the existing
`DL-001`, `DL-007`, and `RESOURCE_NOT_AVAILABLE` behavior is preserved.

Provider access now uses `provider_runtime(state)`. Delivery consumes the
Providers public runtime contract and maps normalized provider failures back to
the existing download contract:

- unavailable/unreachable -> `DL-002`;
- authentication/credential failure -> `DL-006`;
- metadata failure -> `DL-003`;
- provider 429 -> `DL-003` with status 429;
- unknown/configuration failure -> `DL-999`.

`routers/downloads.py` no longer imports shared Resource ORM, calls
`resource_in_publication_scope()`, or resolves connection ORM.

Delivery's download domain no longer imports `AListClient`, `AListError`, or
`decrypt_secret`; it receives a provider-neutral `ProviderEntry` and owns
redirect validation/diagnostic steps only.

This removes the `routers/downloads.py -> cloudsite.models` debt ID and
ratchets architecture debt from 83 to 82.

### R4e — download helper ownership cleanup

Next, make top-level `cloudsite.download` a strict compatibility facade and
move any remaining AList-specific compatibility mapping out of the runtime
Delivery path. Then continue into download event/rate-limit legacy debt.

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
