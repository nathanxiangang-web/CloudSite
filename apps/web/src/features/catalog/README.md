# Catalog Frontend Feature

Migration status: partial.

M6a establishes real ownership for the public /catalog list slice.

Owned here:
- views/CatalogListView.tsx — public list UI
- api.ts — list/search/tag requests
- model.ts — list URL/query/label helpers
- types.ts — list-oriented DTOs
- styles/catalog-list.module.css — list-specific styles
- index.ts — the only public feature entry

The route stays thin and imports only @/features/catalog.

Still legacy and deferred:
- public detail/release/asset view
- follow/subscription UI
- aggregate search Catalog integration
- admin Catalog CRUD/editor
- remaining src/lib/catalog.ts and catalog-client.ts callers

The shared .catalog-card-unavailable rule remains in globals.css temporarily
because the not-yet-migrated detail page still consumes that class.


## M6c-1 Follow ownership

Catalog follow/subscription now belongs to the feature:
- components/CatalogFollowButton.tsx;
- views/CatalogFollowsView.tsx;
- follow status/list DTOs;
- follow/unfollow/notification/list API calls;
- /account/follows route composition.

The legacy components/catalog/CatalogFollowButton.tsx path remains as a
temporary re-export compatibility seam.
