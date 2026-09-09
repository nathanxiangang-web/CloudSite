# CloudSite 1.1 Catalog Contract

This document is the implementation-ready contract for the CloudSite 1.1 Catalog
model and the C1 vertical slice. It is a narrow engineering contract, not a
product roadmap. It is authored against the 1.0.0 stable baseline at commit
`c46a1d94c10d29ba0168f6c5988bc5ce75cdc69c` and cites existing 1.0.0 behavior
where compatibility must be preserved.

The contract defines a Catalog overlay on top of the existing file-level
resource index. The 1.0.0 resource, folder, share, favorite, collection, and
search contracts remain the compatibility baseline and are not redefined here.

## 0. Scope and ground rules

- C1 delivers catalog metadata, public catalog read APIs, and admin catalog
  CRUD APIs. It does not deliver AI, multi-provider aggregation, team roles,
  delivery packages, a page builder, catalog-level favorites, or
  catalog-entry shares.
- The Catalog model is an overlay: every catalog asset location references an
  existing 1.0.0 `resource_id` in `index.db`. The Catalog never owns or moves
  underlying files.
- Publishing a catalog entry does not change the visibility of the underlying
  resource. Resource visibility is still governed by the content root enabled
  state and the resource `status` field, exactly as in 1.0.0.
- Documentation-only contract. No application code, schemas, migrations, tests,
  Compose, version files, or public release docs are changed by this document.

## 1. Terminology

| Term | Definition |
|---|---|
| CatalogEntry | The logical, human-facing catalog item. Example: "Ubuntu 22.04 LTS". Identified by a stable `entry_id`. |
| CatalogRelease | A versioned release of an entry. Example: "22.04.3". Identified by a stable `release_id` and scoped to one entry. |
| CatalogAsset | A concrete file within a release. Example: "ubuntu-22.04.3-desktop-amd64.iso". Identified by a stable `asset_id` and scoped to one release. |
| CatalogLocation | A reference from an asset to one underlying 1.0.0 `resource_id` in a content root. An asset may have multiple locations (mirrors or platform variants). Identified by a stable `location_id`. |
| Tag | An admin-authored label with a stable slug, attachable to entries, releases, and assets. |
| Relation | A typed, directed link between two entries. Example: `supersedes`, `depends`, `companion`. |
| Revision | An append-only audit record of one catalog metadata mutation. Not a file revision; file-level changes remain the responsibility of the 1.0.0 sync index. |
| Publication scope | The set of catalog entries visible to public users and anonymous visitors. Determined by entry `status = published` and at least one active location per asset. |
| Underlying resource | The 1.0.0 `Resource` row in `index.db` referenced by a catalog location. |

### 1.1 Content type alignment

The 1.0.0 content types are `software`, `image`, `video`, `document`, and
`file`, validated by the pattern `^[a-z][a-z0-9_-]{1,39}$` in
`RootMappingInput`. A `CatalogEntry` declares a `content_type` drawn from the
same pattern and namespace. The catalog does not introduce a parallel type
taxonomy; it reuses the content root content types so that a software entry
aligns with the `software` content root.

## 2. State and index ownership

CloudSite 1.0.0 separates authoritative state from the rebuildable index. The
Catalog model preserves and extends this separation.

### 2.1 `state.db` - authoritative catalog metadata

The following catalog tables live in `state.db` and must be backed up. They are
admin-authored metadata and cannot be regenerated from AList or from
`index.db`.

- `catalog_entries`
- `catalog_releases`
- `catalog_assets`
- `catalog_locations`
- `catalog_tags`
- `catalog_tag_assignments`
- `catalog_relations`
- `catalog_revisions`

Loss of `state.db` continues to produce `STATE_RECOVERY_REQUIRED` as in 1.0.0.
The catalog tables are recovered only from a verified backup, never
reconstructed from the index.

### 2.2 `index.db` - rebuildable file index, unchanged

The 1.0.0 `folders`, `resources`, `resource_identity_candidates`, sync, and
FTS tables remain in `index.db` and remain rebuildable. The Catalog model adds
no tables to `index.db`. A catalog location references a `resource_id` in
`index.db` by value; the reference is resolved at read time and is tolerant of
the index being unavailable or rebuilt.

### 2.3 Cross-database consistency rules

1. A `catalog_locations.resource_id` is a foreign key by value to
   `resources.id` in `index.db`. It is not a SQL foreign key because the
   databases are separate SQLite files.
2. If the referenced resource is missing, has `status != active`, or belongs to
   a disabled content root, the location is reported as `unavailable` but the
   catalog metadata row is not deleted.
3. An asset is `available` when at least one of its locations is `available`.
   An entry is `available` when at least one release is `published` and at
   least one asset in that release is `available`.
4. Rebuilding `index.db` (search rebuild or full reindex) must not modify any
   `state.db` catalog table. After a rebuild, locations re-resolve against the
   new `resources` rows.
5. The 1.0.0 `ResourceIdentity` registry in `state.db` remains the source of
   stable resource identity. A catalog location follows the resource identity:
   a reliable rename or move that preserves `resource_id` keeps the location
   valid without any catalog-side update.

## 3. Minimal v1.1 state schema

All IDs are 128-bit random, encoded as a fixed prefix plus 32 lowercase hex
characters, mirroring the 1.0.0 `resource_id` format `r_` + `token_hex(16)`.

| Entity | ID prefix | ID pattern |
|---|---|---|
| CatalogEntry | `ce_` | `ce_` + 32 hex |
| CatalogRelease | `cr_` | `cr_` + 32 hex |
| CatalogAsset | `ca_` | `ca_` + 32 hex |
| CatalogLocation | `cl_` | `cl_` + 32 hex |
| Tag | `ct_` | `ct_` + 32 hex |
| Relation | `cx_` | `cx_` + 32 hex |
| Revision | `cv_` | `cv_` + 32 hex |

Timestamps are timezone-aware UTC, matching the 1.0.0 `utcnow()` convention.

### 3.1 `catalog_entries`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `entry_id` | string(35) | primary key | `ce_` + 32 hex |
| `content_type` | string(40) | not null, pattern `^[a-z][a-z0-9_-]{1,39}$` | aligns with content root types |
| `slug` | string(160) | not null, unique | URL-safe slug, unique across all entries |
| `title` | string(200) | not null | display title |
| `summary` | text | default `''` | short description |
| `description` | text | default `''` | long-form description, Markdown |
| `cover_resource_id` | string(64) | nullable | optional reference to a 1.0.0 `resource_id` used as cover image |
| `status` | string(20) | not null, default `'draft'` | one of `draft`, `published`, `archived`, `disabled` |
| `sort_order` | integer | default `0` | admin-controlled ordering |
| `created_at` | datetime | not null | |
| `updated_at` | datetime | not null | |
| `published_at` | datetime | nullable | set when status transitions to `published` |

Uniqueness: `entry_id` and `slug` are globally unique.

### 3.2 `catalog_releases`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `release_id` | string(35) | primary key | `cr_` + 32 hex |
| `entry_id` | string(35) | not null, index | references `catalog_entries.entry_id` |
| `slug` | string(160) | not null | release slug, e.g. `22.04.3` |
| `title` | string(200) | not null | display title |
| `release_notes` | text | default `''` | Markdown |
| `status` | string(20) | not null, default `'draft'` | one of `draft`, `published`, `archived`, `disabled` |
| `sort_order` | integer | default `0` | |
| `created_at` | datetime | not null | |
| `updated_at` | datetime | not null | |
| `published_at` | datetime | nullable | |

Uniqueness: `release_id` is globally unique. The pair
`(entry_id, slug)` is unique.

### 3.3 `catalog_assets`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `asset_id` | string(35) | primary key | `ca_` + 32 hex |
| `release_id` | string(35) | not null, index | references `catalog_releases.release_id` |
| `slug` | string(160) | not null | asset slug, e.g. `amd64-iso` |
| `display_name` | string(500) | not null | display name |
| `platform` | string(40) | default `''` | optional platform tag, e.g. `amd64`, `arm64`, `universal` |
| `kind` | string(40) | default `'file'` | one of `file`, `document`, `image`, `video`, `archive`, `other` |
| `checksum` | string(200) | nullable | optional verified checksum |
| `checksum_algorithm` | string(20) | nullable | e.g. `sha256` |
| `size` | bigint | nullable | optional authoritative size; falls back to location resource size |
| `status` | string(20) | not null, default `'active'` | one of `active`, `disabled` |
| `sort_order` | integer | default `0` | |
| `created_at` | datetime | not null | |
| `updated_at` | datetime | not null | |

Uniqueness: `asset_id` is globally unique. The pair `(release_id, slug)` is
unique.

### 3.4 `catalog_locations`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `location_id` | string(35) | primary key | `cl_` + 32 hex |
| `asset_id` | string(35) | not null, index | references `catalog_assets.asset_id` |
| `resource_id` | string(64) | not null, index | references 1.0.0 `resources.id` in `index.db` by value |
| `root_mapping_id` | integer | nullable, index | denormalized from the referenced resource for fast filtering |
| `label` | string(100) | default `''` | optional mirror label, e.g. `cn-mirror` |
| `is_primary` | boolean | default `false` | at most one primary location per asset |
| `status` | string(20) | not null, default `'active'` | one of `active`, `disabled` |
| `created_at` | datetime | not null | |
| `updated_at` | datetime | not null | |

Uniqueness: `location_id` is globally unique. The pair
`(asset_id, resource_id)` is unique, so the same resource cannot be attached
to the same asset twice.

The `root_mapping_id` is denormalized from the referenced resource at write
time for filtering. It is not authoritative; the publication layer re-checks
the live content root enabled state at read time.

### 3.5 `catalog_tags`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `tag_id` | string(35) | primary key | `ct_` + 32 hex |
| `slug` | string(60) | not null, unique | URL-safe slug, e.g. `lts` |
| `display_name` | string(100) | not null | |
| `created_at` | datetime | not null | |
| `updated_at` | datetime | not null | |

Uniqueness: `tag_id` and `slug` are globally unique.

### 3.6 `catalog_tag_assignments`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `tag_id` | string(35) | not null | references `catalog_tags.tag_id` |
| `target_type` | string(20) | not null | one of `entry`, `release`, `asset` |
| `target_id` | string(35) | not null | the entity ID |
| `created_at` | datetime | not null | |

Uniqueness: the triple `(tag_id, target_type, target_id)` is unique.

### 3.7 `catalog_relations`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `relation_id` | string(35) | primary key | `cx_` + 32 hex |
| `from_entry_id` | string(35) | not null, index | the subject entry |
| `to_entry_id` | string(35) | not null, index | the object entry |
| `relation_type` | string(40) | not null | e.g. `supersedes`, `depends`, `companion`, `variant` |
| `note` | text | default `''` | |
| `created_at` | datetime | not null | |

Uniqueness: `relation_id` is globally unique. The triple
`(from_entry_id, to_entry_id, relation_type)` is unique.

### 3.8 `catalog_revisions`

Append-only audit log. Rows are inserted, never updated or deleted.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `revision_id` | string(35) | primary key | `cv_` + 32 hex |
| `target_type` | string(20) | not null | one of `entry`, `release`, `asset`, `location`, `tag`, `relation` |
| `target_id` | string(35) | not null | the entity ID |
| `action` | string(40) | not null | one of `create`, `update`, `delete`, `publish`, `unpublish`, `archive`, `disable` |
| `actor` | string(100) | not null | admin username or `system` |
| `payload_json` | text | default `'{}'` | snapshot of changed fields |
| `created_at` | datetime | not null | |

### 3.9 Status transitions

Entry and release status transitions follow this directed graph:

```text
draft -> published
published -> draft
published -> archived
archived -> published
published -> disabled
disabled -> published
draft -> disabled
disabled -> draft
```

`delete` is a hard delete available only when the entity has no published
children (for entries: no published releases; for releases: no assets with
active locations). A soft `archived` or `disabled` status is preferred for
reversibility.

## 4. Minimal admin API surface

All admin routes require an administrator session, matching the 1.0.0
`ADMIN_REQUIRED` enforcement. Errors use the 1.0.0 error envelope
`{"detail": {"code": "...", "message": "..."}}`.

### 4.1 Admin catalog routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/catalog/entries` | List entries (all statuses) |
| `POST` | `/api/admin/catalog/entries` | Create an entry |
| `GET`, `PATCH`, `DELETE` | `/api/admin/catalog/entries/{entry_id}` | Read, update, or delete an entry |
| `GET` | `/api/admin/catalog/entries/{entry_id}/releases` | List releases for an entry |
| `POST` | `/api/admin/catalog/entries/{entry_id}/releases` | Create a release |
| `GET`, `PATCH`, `DELETE` | `/api/admin/catalog/releases/{release_id}` | Read, update, or delete a release |
| `GET` | `/api/admin/catalog/releases/{release_id}/assets` | List assets for a release |
| `POST` | `/api/admin/catalog/releases/{release_id}/assets` | Create an asset |
| `GET`, `PATCH`, `DELETE` | `/api/admin/catalog/assets/{asset_id}` | Read, update, or delete an asset |
| `GET` | `/api/admin/catalog/assets/{asset_id}/locations` | List locations for an asset |
| `POST` | `/api/admin/catalog/assets/{asset_id}/locations` | Attach a location |
| `PATCH`, `DELETE` | `/api/admin/catalog/locations/{location_id}` | Update or detach a location |
| `GET`, `POST` | `/api/admin/catalog/tags` | List or create a tag |
| `PATCH`, `DELETE` | `/api/admin/catalog/tags/{tag_id}` | Update or delete a tag |
| `POST`, `DELETE` | `/api/admin/catalog/tag-assignments` | Assign or remove a tag |
| `GET`, `POST` | `/api/admin/catalog/relations` | List or create a relation |
| `DELETE` | `/api/admin/catalog/relations/{relation_id}` | Delete a relation |
| `GET` | `/api/admin/catalog/revisions` | List revisions (paginated, filterable by `target_type`, `target_id`) |

`PATCH` on an entry, release, asset, location, or tag accepts a partial body
and creates a `catalog_revisions` row. `DELETE` on an entry or release is
rejected if published children exist and returns
`CATALOG_DELETE_CONFLICT`.

### 4.2 Compatibility with existing admin routes

The 1.0.0 admin routes in `docs/contracts.md` section 1.3 are unchanged. The
catalog admin routes are additive and do not alter `root-mappings`,
`collections`, `shares`, `sync`, `search/rebuild`, `identities`, or `system`
behavior.

## 5. Minimal public API surface

### 5.1 Public catalog routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/catalog/entries` | List published entries (paginated, filterable by `content_type`, `tag`) |
| `GET` | `/api/catalog/entries/{entry_id}` | Published entry detail with releases and asset summaries |
| `GET` | `/api/catalog/entries/{entry_id}/releases` | Published releases for an entry |
| `GET` | `/api/catalog/releases/{release_id}` | Published release detail with assets |
| `GET` | `/api/catalog/assets/{asset_id}` | Published asset detail with available locations |
| `GET` | `/api/catalog/search` | Search published entries by text |
| `GET` | `/api/catalog/tags` | List tags used by at least one published entry |

Public routes return `404` with `CATALOG_ENTRY_NOT_FOUND` (or the
release/asset equivalent) for draft, archived, disabled, or nonexistent
targets. They never reveal the existence of unpublished entries to public
users or anonymous visitors.

### 5.2 Asset download

Asset download reuses the 1.0.0 transfer contract. The public asset detail
returns a `download_url` of `/d/{resource_id}` for each available location,
where `resource_id` is the underlying 1.0.0 resource. The actual redirect is
handled by the existing 1.0.0 `/d/{resource_id}` route, which returns HTTP 302
to an AList-native entry. CloudSite does not proxy file bodies.

A `primary` location is preferred when a client requests a single download URL.
If no location is marked primary, the first available location is used.

### 5.3 Compatibility behavior for existing 1.0.0 surfaces

| Surface | Compatibility behavior |
|---|---|
| File resources (`/api/resources`, `/api/resources/{id}`, `/resource/{id}`) | Unchanged. Catalog is an overlay; the 1.0.0 resource list and detail pages continue to work and are not redirected to catalog pages. |
| Download gateway (`/d/{resource_id}`, `/p/{resource_id}`) | Unchanged. Catalog asset downloads reuse these routes by value. |
| Search (`/api/search`) | Unchanged. The 1.0.0 search continues to return `resource` and `folder` objects. Catalog entries are not injected into 1.0.0 search results. A separate `/api/catalog/search` is provided. Merging the two is deferred beyond C1. |
| Favorites (`/api/me/favorites*`) | Unchanged. Favorites remain scoped to 1.0.0 `resource_id`. C1 does not introduce catalog-level favorites. A favorite on a resource that is also a catalog asset continues to resolve to the resource. |
| Collections (`/api/collections*`, `/api/admin/collections*`) | Unchanged. Collection items reference 1.0.0 `resource_id`. A collection item that is also a catalog asset still appears in the collection as a resource. C1 does not auto-promote collection items to catalog entries. |
| Shares (`/api/my/shares`, `/api/admin/shares`, `/s/{token}`) | Unchanged. Shares remain scoped to 1.0.0 `object_type` of `resource`, `folder`, or `collection`. A share on a resource that is also a catalog asset still works and still resolves to the resource. C1 does not introduce catalog-entry shares. |
| Home (`/api/home`) | Unchanged shape. The home page continues to show content roots, recent resources, popular resources, and collections. Catalog entries are not injected into the home page in C1. |
| Content roots (`/api/content-roots`, `/api/admin/root-mappings`) | Unchanged. Content root enable/disable continues to govern resource visibility. Disabling a root suppresses all catalog locations that reference resources in that root. |
| Office/PDF/video preview | Unchanged. Catalog asset preview reuses the 1.0.0 preview endpoints by `resource_id`. No new preview pipeline is introduced. |

## 6. Page information architecture

### 6.1 New public pages

| Path | Purpose |
|---|---|
| `/catalog` | List of published catalog entries, filterable by content type and tag |
| `/catalog/[entry_id]` | Entry detail: summary, releases, assets, tags, relations |
| `/catalog/releases/[release_id]` | Release detail: release notes, assets, locations |
| `/catalog/assets/[asset_id]` | Asset detail: metadata, available locations, download, preview |

### 6.2 New admin pages

| Path | Purpose |
|---|---|
| `/admin/catalog` | Catalog management overview |
| `/admin/catalog/entries` | Entry list and create |
| `/admin/catalog/entries/[entry_id]` | Entry editor: releases, assets, tags, relations, revisions |

### 6.3 Existing pages unchanged

The 1.0.0 pages (`/`, `/resources/[type]`, `/resource/[id]`, `/folder/[id]`,
`/collections`, `/search`, `/account/*`, `/admin/*` except catalog,
`/s/{token}`, `/login`, `/register`, `/about`, `/privacy`, `/terms`, `/submit`,
`/submissions`, `/download-error`) are unchanged in C1. The catalog pages are
additive.

## 7. Acceptance scenarios

Each scenario has a stable identifier, a setup, an action, and an expected
outcome. Scenarios are stated against a system upgraded from 1.0.0 to 1.1.0
with the catalog schema migrated and at least one enabled content root
populated by a successful initial synchronization.

### S-01 Software release with multiple platform files

- **Identifier**: `S-01-multi-platform-software`
- **Setup**: One enabled `software` content root. A directory containing
  `ubuntu-22.04.3-desktop-amd64.iso`, `ubuntu-22.04.3-desktop-arm64.iso`, and
  `SHA256SUMS`, all indexed as 1.0.0 resources with stable `resource_id`
  values.
- **Action**: An administrator creates one entry `ce_...` with content type
  `software`, one release `cr_...`, and three assets. Each asset has one
  location referencing the corresponding `resource_id`. The entry and release
  are set to `published`.
- **Expected outcome**: `GET /api/catalog/entries/{entry_id}` returns the entry
  with the release and three assets. Each asset exposes a `download_url` of
  `/d/{resource_id}`. The entry page `/catalog/[entry_id]` lists all three
  assets. Downloading each asset performs an HTTP 302 to the AList-native
  entry, reusing the 1.0.0 transfer path. The three files are not
  automatically grouped by filename; the admin explicitly created three
  assets.

### S-02 Tutorial and material entry with preview compatibility

- **Identifier**: `S-02-tutorial-materials-preview`
- **Setup**: One enabled `document` content root. A markdown tutorial
  `intro.md`, a PDF `guide.pdf`, and an MP4 `walkthrough.mp4` are indexed.
- **Action**: An administrator creates an entry with content type `document`,
  one release, and three assets referencing the three resources. The entry is
  left in `draft` status.
- **Expected outcome**: The entry is not visible on `/api/catalog/entries`,
  `/api/catalog/search`, or the `/catalog` page. An anonymous request to
  `/api/catalog/entries/{entry_id}` returns `404` with
  `CATALOG_ENTRY_NOT_FOUND`. After the admin sets the entry to `published`,
  the entry is visible. Asset preview reuses the 1.0.0
  `/api/resources/{resource_id}/preview`, `text-preview`, `pdf-preview`, and
  `office-preview` endpoints by `resource_id`; no new preview pipeline is
  exercised. Video preview behavior is unchanged from 1.0.0 and depends on
  browser-native decoding.

### S-03 Reliable move preserves catalog links

- **Identifier**: `S-03-reliable-move-preserves-links`
- **Setup**: An entry with one published release and one asset with one
  location referencing `resource_id = r_abc`. The underlying file is reliably
  renamed in AList and the rename is detected by the rolling sync as a move
  (not a copy), preserving the `resource_id` per the 1.0.0 identity contract.
- **Action**: No catalog-side action. The sync cycle completes.
- **Expected outcome**: The catalog location remains valid because
  `resource_id` is unchanged. `GET /api/catalog/assets/{asset_id}` still
  returns the asset with an available location. All 1.0.0 links (`/d/r_abc`,
  `/resource/r_abc`), shares, and favorites on `r_abc` remain valid. No
  `catalog_revisions` row is created by the move; file-level identity is the
  responsibility of the 1.0.0 index, not the catalog.

### S-04 Same-name files in different folders

- **Identifier**: `S-04-same-name-distinct-resources`
- **Setup**: Two files named `README.md` in two different folders, indexed as
  two distinct 1.0.0 resources `r_one` and `r_two` with distinct paths. The
  1.0.0 `resources.path` unique constraint guarantees the two rows are
  distinct.
- **Action**: An administrator creates one asset with two locations, one
  referencing `r_one` and one referencing `r_two`.
- **Expected outcome**: Both locations are accepted because the pair
  `(asset_id, resource_id)` is unique and the two `resource_id` values differ.
  The asset has two available locations. The catalog does not automatically
  group the two files by filename; the admin explicitly chose to attach both.
  Alternatively, the admin could create two separate assets, each with one
  location. Both configurations are valid and produce different catalog
  output.

### S-05 Path reuse after deletion

- **Identifier**: `S-05-path-reuse-new-identity`
- **Setup**: A file at path `/root/old.txt` is indexed as `r_old`. The file is
  deleted from AList and the deletion is confirmed across two independent sync
  cycles, so `r_old` becomes `missing`. A new file is then created at the same
  path `/root/old.txt` and is indexed as a new resource `r_new` with a new
  `resource_id`, per the 1.0.0 identity contract (path reuse receives a new
  ID).
- **Action**: A catalog location previously referenced `r_old`. No automatic
  re-linking occurs.
- **Expected outcome**: The location referencing `r_old` is `unavailable`
  because `r_old` is `missing`. The asset is `unavailable` if it has no other
  active location. The entry remains visible but is marked unavailable. The
  new `r_new` is not automatically attached to the existing asset. The admin
  must explicitly create a new location referencing `r_new`, or create a new
  asset. This preserves the 1.0.0 guarantee that path reuse does not silently
  merge identities.

### S-06 Cross-root and disabled content

- **Identifier**: `S-06-cross-root-disabled-suppression`
- **Setup**: Two enabled content roots, `software` (root id 1) and `archive`
  (root id 2). An asset has two locations: `cl_a` referencing a resource in
  root 1 and `cl_b` referencing a resource in root 2. The entry is published.
- **Action**: The administrator disables root 2 via
  `PATCH /api/admin/root-mappings/2` (existing 1.0.0 route).
- **Expected outcome**: `cl_b` is suppressed because its referenced resource's
  root is disabled. `cl_a` remains available. The asset is still `available`
  via `cl_a`. The entry is still visible. If root 1 is also disabled, both
  locations are suppressed, the asset is `unavailable`, and the entry is
  visible but marked unavailable. No underlying files are moved. Re-enabling a
  root immediately restores the suppressed locations without any catalog-side
  write.

### S-07 Old file links remain valid

- **Identifier**: `S-07-old-file-links-valid`
- **Setup**: A 1.0.0 resource `r_xyz` is browsable at `/resource/r_xyz` and
  downloadable at `/d/r_xyz`. The resource is later attached to a catalog
  asset as a location.
- **Action**: A user visits `/resource/r_xyz` and `/d/r_xyz` after the catalog
  link is created.
- **Expected outcome**: `/resource/r_xyz` returns the 1.0.0 resource detail
  page unchanged; it is not redirected to `/catalog/assets/{asset_id}`.
  `/d/r_xyz` returns the HTTP 302 download redirect unchanged. The 1.0.0
  `resource_id` is not redefined or remapped. The catalog link is an
  additional reference, not a replacement of the 1.0.0 surface.

### S-08 Old shares remain valid

- **Identifier**: `S-08-old-shares-valid`
- **Setup**: A 1.0.0 share `s_old` is created on `object_type = resource`,
  `object_id = r_xyz`. The resource is later attached to a catalog asset.
- **Action**: An anonymous visitor opens `/s/s_old` and downloads via
  `/s/s_old/d`.
- **Expected outcome**: The share still works, still resolves to `r_xyz`, and
  still enforces its original scope, expiry, access code, and download limit.
  The share is not automatically re-scoped to the catalog entry or asset. The
  share token is unchanged. C1 does not introduce catalog-entry shares; the
  1.0.0 share contract in `docs/contracts.md` section 8 is preserved.

### S-09 Old favorites remain valid

- **Identifier**: `S-09-old-favorites-valid`
- **Setup**: A 1.0.0 user has a favorite on `r_xyz`. The resource is later
  attached to a catalog asset.
- **Action**: The user opens `/account/favorites`.
- **Expected outcome**: The favorite still resolves to `r_xyz` and appears in
  the favorite list unchanged. The favorite is not automatically migrated to a
  catalog-entry favorite. C1 does not introduce catalog-level favorites; the
  1.0.0 favorite contract on `UserFavorite(user_id, resource_id)` is preserved.

### S-10 Publishing does not make content anonymous-public

- **Identifier**: `S-10-publish-not-anonymous-public`
- **Setup**: A site with the default protected configuration requiring a
  public-user session outside the anonymous allowlist. A resource `r_priv` in
  an enabled content root. An entry is created in `draft` status with an asset
  location referencing `r_priv`.
- **Action**: The admin sets the entry to `published`. The underlying resource
  `r_priv` remains governed by its content root.
- **Expected outcome**: The catalog entry is visible to authenticated public
  users on `/catalog` and `/api/catalog/entries`. The entry is not visible to
  anonymous visitors if the site requires a session, because the catalog
  public routes respect the 1.0.0 authentication boundary. Publishing the
  catalog entry does not change the visibility of `r_priv` on the 1.0.0
  resource surface; `r_priv` continues to follow the content root enabled
  state and the site authentication boundary. If the content root is later
  disabled, the catalog location is suppressed even though the entry remains
  `published`. Publishing is a necessary but not sufficient condition for
  public availability.

## 8. Acceptance criteria

### 8.1 Normal operation

- An admin can create an entry, release, asset, and location through the admin
  API, and each mutation creates a `catalog_revisions` row.
- After setting entry and release to `published`, the entry appears in
  `GET /api/catalog/entries` and `GET /api/catalog/search`.
- The entry detail includes releases, assets, and available locations.
- Asset `download_url` values point to existing 1.0.0 `/d/{resource_id}`
  routes and perform HTTP 302 redirects.
- Tags and relations are readable on the entry detail and filterable on the
  entry list.

### 8.2 Failure operation

- If a referenced resource is `missing` or has `status != active`, the
  location is `unavailable`; the asset is `unavailable` if no location is
  available; the entry remains visible but is marked unavailable.
- If AList is unavailable, catalog browse and search continue from `state.db`
  and `index.db`. Downloads and previews return controlled errors via the
  existing 1.0.0 error envelope. No catalog metadata is lost.
- If `index.db` is unavailable, catalog metadata in `state.db` remains intact.
  Location resolution fails gracefully; entries are listed but assets are
  marked unavailable. This mirrors the 1.0.0 `INDEX_RECOVERY` behavior.

### 8.3 Migration

- Upgrading from 1.0.0 to 1.1.0 runs a forward-only, idempotent schema
  migration on `state.db` that creates the catalog tables. The migration
  follows the existing `migrations.py` chain pattern and increments
  `schema_version`.
- The migration does not modify any existing 1.0.0 table, row, or route.
- The migration does not create any catalog entries automatically. The catalog
  is empty after migration.
- If the migration fails, the API does not start, matching the 1.0.0 migration
  failure behavior. A verified backup restore is the recovery path.
- `index.db` schema is unchanged; no index migration is required.

### 8.4 Rebuild

- `POST /api/admin/search/rebuild` rebuilds the 1.0.0 FTS index and does not
  touch `state.db` catalog tables.
- A full `index.db` rebuild (recovery from `INDEX_RECOVERY`) preserves all
  catalog metadata. After the rebuild, locations re-resolve against the new
  `resources` rows. A location whose `resource_id` no longer exists in the
  rebuilt index is `unavailable` until the admin re-links it.
- Catalog metadata is never reconstructed from the index. The catalog is an
  overlay, not a derivative of the index.

### 8.5 Backup and export

- The existing `scripts/backup.sh` includes `state.db` and therefore includes
  all catalog tables. No backup script change is required for C1.
- A restore from a 1.1.0 backup restores catalog metadata intact.
- The admin API provides `GET /api/admin/catalog/revisions` for audit export.
  A separate bulk catalog export endpoint is deferred beyond C1; the revisions
  log plus the current state of each entity is sufficient for C1 audit and
  portability.
- Backups continue to contain encrypted credentials and key material and must
  use restricted access, as in 1.0.0.

### 8.6 Authorization scope

- All `/api/admin/catalog/*` routes require an administrator session. Missing
  or invalid sessions return `ADMIN_REQUIRED` with HTTP 403, matching 1.0.0.
- All `/api/catalog/*` public routes return only `published` entries, releases,
  and assets with at least one available location. Draft, archived, and
  disabled entities are not visible to public users or anonymous visitors.
- Public catalog routes respect the 1.0.0 authentication boundary: if the site
  requires a public-user session, anonymous access to `/api/catalog/*` is
  rejected unless the route is added to the explicit anonymous allowlist. C1
  does not add catalog routes to the anonymous allowlist by default.
- Content root disablement suppresses locations regardless of catalog entry
  status. An admin cannot bypass a disabled content root by publishing a
  catalog entry that references a resource in that root.
- The catalog never exposes `provider_object_id`, `content_hash`, AList
  credentials, or internal filesystem paths beyond what the 1.0.0 resource
  surface already exposes, matching the 1.0.0 information-disclosure rules.

### 8.7 Rollback

- Image-only rollback from 1.1.0 to 1.0.0: the 1.0.0 image ignores the catalog
  tables in `state.db`. The 1.0.0 routes, resource surface, shares, favorites,
  and collections continue to work. The catalog tables are inert unused rows.
- Data rollback to a 1.0.0 backup (taken before the 1.1.0 migration) removes
  the catalog tables because they did not exist in 1.0.0. The 1.0.0 state is
  intact. Catalog metadata created after the migration is lost; this is
  expected because catalog metadata is authoritative state and cannot be
  reconstructed from the index.
- Data rollback to a 1.1.0 backup restores catalog metadata intact. The
  restore process retains a rollback copy, as in 1.0.0.
- Rollback does not require moving underlying files or modifying AList.

## 9. Decisions deferred beyond C1

The following are explicitly out of scope for C1 and require a separate
contract before implementation:

- AI recommendations, OCR indexing, and automatic metadata extraction.
- Multi-provider catalog aggregation across AList instances.
- Team roles and multi-user catalog authoring workflows.
- Delivery packages and bundled or archived multi-asset downloads.
- Page builder and custom entry layouts.
- Catalog-level favorites, history, and playback progress.
- Catalog-entry and catalog-release shares (shares remain 1.0.0
  resource/folder/collection scoped).
- Automatic filename grouping into entries or assets.
- Moving or renaming underlying files from the catalog admin surface.
- Anonymous-public publishing of underlying resources bypassing the site
  authentication boundary.
- Cross-instance catalog synchronization.
- Versioned tag taxonomies, tag namespaces, and tag inheritance.
- Catalog entry comments, ratings, and community submissions.
- Automatic catalog entry creation from indexed files.
- Merging 1.0.0 resource search and 1.1.0 catalog search into a single
  endpoint.
- Catalog-driven home page sections and curated catalog carousels.
- Per-asset download limits and per-asset access codes distinct from the 1.0.0
  share contract.

## 10. References to 1.0.0 baseline

This contract cites the following 1.0.0 surfaces as compatibility anchors. All
are read-only references and are not modified by this document.

- `docs/contracts.md` - HTTP routes, error envelope, environment variables,
  data ownership, transfer contract, authentication contract, share contract.
- `docs/architecture.md` - system overview, transfer semantics, database
  ownership, synchronization model, stable resource identity.
- `docs/limitations.md` - generic AList is not a delta provider, folder IDs
  may be path-derived, ambiguous identity resolution.
- `docs/deployment-upgrade-backup.md` - backup, restore, upgrade, rollback.
- `docs/operations-disaster-recovery.md` - data responsibilities, recovery
  priorities.
- `docs/recovery-guide.md` - `INDEX_RECOVERY` and `STATE_RECOVERY_REQUIRED`
  behavior.
- `apps/api/cloudsite/models.py` - `ResourceIdentity`, `Resource`,
  `ContentRootMapping`, `Share`, `UserFavorite`, `Collection`,
  `CollectionItem` schemas.
- `apps/api/cloudsite/identity/service.py` - `resource_id` format
  `r_` + `token_hex(16)` and conservative identity resolution.
- `apps/api/cloudsite/migrations.py` - forward-only idempotent migration
  chain, `schema_version` storage.
- `apps/api/cloudsite/shares/service.py` - `DURATION_OPTIONS`,
  `ShareStatus`, `MAX_SHARE_DOWNLOADS`, publication scope checks.
