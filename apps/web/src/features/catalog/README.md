# Catalog Frontend Feature

Migration status: partial.

M6a establishes real ownership for the public /catalog list slice.
M6b adds the public /catalog/[entryId] detail/release/asset slice.

Owned here:
- views/CatalogListView.tsx — public list UI
- api.ts — list/search/tag requests
- model.ts — list URL/query/label helpers
- types.ts — list-oriented DTOs
- styles/catalog-list.module.css — list-specific styles
- views/CatalogDetailView.tsx — public detail/release/asset UI
- styles/catalog-detail.module.css — public detail styles
- detail DTOs/helpers/API calls in types.ts/model.ts/api.ts
- index.ts — the only public feature entry

The route stays thin and imports only @/features/catalog.

Still legacy and deferred:
- follow/subscription UI
- aggregate search Catalog integration
- admin Catalog CRUD/editor
- remaining src/lib/catalog.ts and catalog-client.ts callers

The public detail slice no longer depends on Catalog-specific global styles.
Follow remains route-injected until M6c.
