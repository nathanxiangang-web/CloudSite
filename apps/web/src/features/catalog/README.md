# Catalog Frontend Feature

Migration status: partial.

## Owned by this feature

Public routes:
- `/catalog` — list/search/filter view
- `/catalog/[entryId]` — detail/release/asset/download view
- `/account/follows` — signed-in Catalog follows list

Feature-owned code:
- `views/CatalogListView.tsx`
- `views/CatalogDetailView.tsx`
- `views/CatalogFollowsView.tsx`
- `components/CatalogFollowButton.tsx`
- `api.ts` — public Catalog and follow/subscription requests
- `model.ts` — pure URL, label, release, and asset helpers
- `types.ts` — Catalog list/detail/follow DTOs
- `styles/catalog-list.module.css`
- `styles/catalog-detail.module.css`
- `index.ts` — the only public feature entry

Application routes should compose the feature through `@/features/catalog`
rather than importing feature internals.

## Compatibility seams

`src/components/catalog/CatalogFollowButton.tsx` remains temporarily as a
re-export of the feature-owned component so old imports can be removed
incrementally.

## Still legacy / next slices

- aggregate `/search` Catalog integration still imports `src/lib/catalog*`
- admin Catalog CRUD/editor still imports `src/lib/catalog*`
- account/search/admin call sites must move before the legacy Catalog libs can
  be retired

M6c-2 should migrate aggregate search. M6d should migrate Admin Catalog, then
the remaining legacy Catalog helper/client surfaces can be deleted.
