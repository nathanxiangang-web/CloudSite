# Catalog Module

## Responsibility

Catalog entries, metadata, releases, follow/subscription, and publication
scope. This module is the editorial layer over resources: it groups resources
into catalog entries (e.g., a series, a movie, an album), attaches rich
metadata, manages release versions, and lets users follow entries to receive
notifications on new releases.

Core duties:
- Catalog entry CRUD and publication scope management.
- Metadata extraction and revision history.
- Release management (version, assets, locations).
- Tag assignment and relation graph between entries.
- User follow/subscription and release notifications.
- Search projection outbox for the search module.

## Public API

- `create_entry(resource_id, metadata)` - create a catalog entry.
- `update_metadata(entry_id, metadata)` - revision-tracked update.
- `publish_release(entry_id, release)` - publish a new release version.
- `follow_entry(user_id, entry_id)` / `unfollow_entry(...)`.
- `list_releases(entry_id)` / `get_entry(entry_id)`.
- `assign_tags(entry_id, tags)` / `set_relation(entry_a, entry_b, kind)`.

Exports live in `contracts/public.py`. The `public/` directory holds the
entry and release schemas.

## Domain Model

- CatalogEntry (id, resource_id, title, scope, status, created_at)
- CatalogMetadata (entry_id, fields, revision_id)
- CatalogRelease (id, entry_id, version, assets, published_at)
- CatalogAsset (release_id, kind, resource_id)
- CatalogLocation (release_id, provider_id, path)
- CatalogTag (id, name) / CatalogTagAssignment (entry_id, tag_id)
- CatalogRelation (entry_a, entry_b, relation_kind)
- CatalogRevision (entry_id, revision_id, diff, author, at)
- CatalogFollow (user_id, entry_id, created_at)

## Database Tables

Catalog-owned state tables:
- `catalog_entries`, `catalog_releases`, `catalog_assets`, `catalog_locations`
- `catalog_tags`, `catalog_tag_assignments`, `catalog_relations`
- `catalog_revisions` - metadata revision history.
- `catalog_search_outbox` - Catalog-owned projection outbox.
- `catalog_favorites`, `catalog_subscriptions` - user engagement.
- `catalog_release_notifications` - release-notification dedup records.

`catalog_search_projection_state` is Search-owned. `catalog_suggestions` is
Automation-owned. Catalog does not claim either table.

## Dependencies

- platform/db
- platform/tasks
- modules/resources (via contracts) - resource state validation.
- modules/providers (via contracts) - enabled publication roots.
- modules/notifications (via contracts) - release notifications.

Search consumes the Catalog-owned outbox; Catalog does not depend on Search.

## Events/Tasks

- Emits `catalog.metadata_changed`, `catalog.release_published`.
- Enqueues metadata extraction and search projection tasks.
- Consumes `indexing.change_detected` to refresh entry resource links.
- Release notifications fan out via the notifications module.

## Security

- Publication scope enforces who can see an entry (public, unlisted, private).
- Metadata edits require editor or admin role; tracked in revisions.
- Follow/subscription is user-scoped; one user cannot read another's follows.
- Suggestion application requires editor approval; never auto-applied.

## Failure Modes

- Source resource deleted: entry marked `source_gone`; editor resolves.
- Revision conflict: optimistic locking on metadata; last writer retries.
- Projection outbox backlog: eventual consistency; search lags until drained.
- Release with no assets: rejected at publish time with a validation error.

## Tests

- `tests/unit/` - metadata revision diff, scope checks, relation graph.
- `tests/contract/` - entry and release schema stability.
- Target coverage: publication scope, revision history, follow lifecycle.

## Do Not

- Do not store raw file bytes; reference resources by ID.
- Do not auto-apply AI suggestions; require editor approval.
- Do not bypass publication scope in any query.
- Do not write to the FTS index directly; use the outbox pattern.

## Current Migration Status

Migration status: partial.

C5a moved the 12 Catalog-owned state ORM declarations into
`modules/catalog/infrastructure/models.py`; `cloudsite.models` keeps exact
compatibility re-exports.

`catalog_entry.py` and `catalog_release.py` no longer import shared
`cloudsite.models` or `cloudsite.services`. Resource state comes through
Resources contracts, enabled publication roots through Providers contracts,
and release notifications through Notifications contracts.

Revision writes, search-outbox enqueue, and release-subscriber notification
write-side helpers now live in the Catalog module. Legacy `services/catalog*`
read/search/follow compatibility surfaces and the public/admin Catalog routers
remain migration work; Catalog should not yet be described as isolated.

## Public Query Ownership

Public entry/release/asset projections now live in
`application/public_queries.py` and are exported through the Catalog public
contract. The legacy `services/catalog_views.py` module is a compatibility shim
only.

Catalog resource availability is resolved through the Resources contract using
persistence-neutral DTOs. The public Catalog download route also resolves the
underlying resource through Resources and passes the Providers runtime gateway
to Delivery's download resolver; it no longer passes an `AListConnection` ORM
object into a `ProviderRuntimePort` API.

The authenticated public Catalog router now has zero tracked ORM-import debt.

## Publication Scope Ownership

Catalog now owns publication visibility in
`application/publication_scope.py`.

- admin publication-scope list/toggle operations are module-owned;
- public Catalog DTO generation is module-owned and excludes management fields;
- publication-scope audit logging is written through platform observability;
- sitemap helpers and cache state live with Catalog;
- `services/publication_scope.py` is a compatibility shim for the existing
  sitemap route and legacy tests;
- `routers/admin/publication_scope.py` contains no direct ORM/SQLAlchemy
  access.

## Admin Boundary Ownership

Admin Catalog list/detail/release/asset/location projections now live in
`application/admin_facade.py` and are exported only through
`contracts/public.py`. Release/asset/location deletion is module-owned as
well. The admin Catalog router no longer imports shared ORM models or
SQLAlchemy and acts only as an HTTP boundary.

Legacy `services/catalog.py` remains a compatibility shim for older call
sites, but new admin code must use the Catalog public contract.

