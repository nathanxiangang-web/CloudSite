# Catalog Frontend Feature

Migration status: partial.

M6a moves the public /catalog list route into the feature boundary while
preserving its existing API calls, React Query behavior, markup, and CSS class
names.

Current ownership:
- views/CatalogListView.tsx: public catalog list UI
- index.ts: public feature entry

Still legacy and intentionally deferred:
- lib/catalog.ts types/helpers
- lib/catalog-client.ts public/admin/follow API calls
- components/catalog/CatalogFollowButton.tsx
- /catalog/[entryId] detail route
- /admin/catalog routes
- existing catalog-specific rules inside app/globals.css

Those slices move incrementally in M6b/M6c rather than being rewritten at once.
