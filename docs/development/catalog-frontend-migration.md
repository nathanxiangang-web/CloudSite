# Catalog Frontend Migration

> **Historical execution record.** This document preserves the slice-by-slice migration plan and invariants at the time it was written. It is not the current backlog. Before acting on any `Next`, `Then`, or `Later` item here, check `module.yaml`, the module `README.md`, [modularization-status.md](./modularization-status.md), and issue #157 against current `main`.


## M6a — Public list ownership

The main branch already moved the /catalog route into features/catalog. This
follow-up completes real feature ownership rather than stopping at a directory
move.

M6a now owns:
- list/search/tag DTOs and API calls;
- list query/URL/label helpers;
- CatalogListView;
- list CSS module.

The view no longer imports the legacy @/lib/catalog or @/lib/catalog-client.

Catalog list CSS is removed from app/globals.css. The shared unavailable badge
rule remains temporarily because the legacy detail page still uses it.

Later slices:
- M6b public detail/release/asset;
- M6c follow/subscription;
- M6d admin Catalog;
- final retirement of legacy src/lib/catalog*.


Compatibility note: the legacy `.catalog-card-unavailable` selector remains
global because the not-yet-migrated Catalog detail route still consumes it.
It moves with the detail slice rather than being removed prematurely.
