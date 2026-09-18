# Catalog Frontend Migration

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


## M6b — Public detail/release/asset slice

The dynamic Catalog detail route now composes `CatalogDetailView` through the
feature public entry. The feature owns entry/release API calls, detail DTOs,
release-selection helpers, asset filters/download-path construction, and its
detail CSS module.

The legacy Follow component remains outside the feature and is injected by the
route as a slot, avoiding a reverse dependency from the feature into the old
business component tree.

Only detail-owned global selectors are removed. Admin Catalog selectors remain
global until the Admin slice migrates.


### M6b CSS ratchet

After moving the detail-owned selectors into
`features/catalog/styles/catalog-detail.module.css`:

- M6a baseline: **151,484 bytes**
- M6b baseline: **149,456 bytes**
- M6b reduction: **2,028 bytes**
- cumulative reduction from M5 baseline (153,299): **3,843 bytes**


## M6c-1 — Follow and account-follows slice

Catalog follow status, follow/unfollow, notification preference, and
`/account/follows` list behavior now live in the Catalog feature.

`CatalogDetailView` consumes the feature-owned Follow button directly, while
the old `components/catalog/CatalogFollowButton.tsx` file is reduced to a
temporary public-entry re-export. The account route becomes shell composition
only.
