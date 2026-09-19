# Catalog Module Migration

Catalog is the editorial layer over Resources. It owns catalog entry/release/
asset/location metadata, revision history, user follows/subscriptions, release
notification dedup state, and the search projection **outbox**.

Search owns projection state/FTS consumption. Automation owns
`catalog_suggestions`.

## C5a — core shared-core debt closure

Status: implemented.

### ORM ownership

The following state tables are now declared in
`modules/catalog/infrastructure/models.py`:

- catalog_entries
- catalog_releases
- catalog_assets
- catalog_locations
- catalog_tags
- catalog_tag_assignments
- catalog_relations
- catalog_revisions
- catalog_search_outbox
- catalog_favorites
- catalog_subscriptions
- catalog_release_notifications

`cloudsite.models` re-exports the exact same class objects. No schema migration
is intended.

### Cross-module state

Catalog no longer imports Provider or Resource ORM.

Publication-root scope comes from:

```text
modules/providers/contracts/public.py
  -> enabled_root_ids(session)
```

Resource validation comes from:

```text
modules/resources/contracts/public.py
  -> resource_queries(index).catalog_resource(...)
  -> CatalogResourceView(id, status, root_mapping_id, content_type)
```

The view is deliberately narrow and does not expose storage path, provider
credentials, or ORM objects.

### Catalog-owned write side

The core application now uses module-local helpers for:

- revision append;
- search projection outbox enqueue;
- release subscriber notification orchestration.

Release notification creation crosses the Notifications public contract and
remains inside the caller-owned Catalog transaction.

### Architecture debt

This removes all four tracked Catalog module legacy imports:

```text
catalog_entry.py   -> cloudsite.models
catalog_entry.py   -> cloudsite.services
catalog_release.py -> cloudsite.models
catalog_release.py -> cloudsite.services
```

Global ratchet:

```text
71 -> 67
module_legacy_import: 16 -> 12
router_orm_import: 55
```

The remaining 12 module legacy-import debts are all in Automation.

## C5b — legacy Catalog service decomposition

Next:

- move remaining metadata/follow/search-view compatibility service ownership
  behind Catalog contracts;
- keep Search projection consumption on the Search side;
- preserve the Catalog outbox as the only Catalog -> Search handoff;
- migrate release/follow producers to module commands without duplicating
  write-side behavior.

## C5c — Catalog router thinning

After service ownership is stable:

- remove ORM/SQLAlchemy from `routers/catalog.py`;
- remove ORM/SQLAlchemy from `routers/admin/catalog.py`;
- move view composition/count/delete helpers into Catalog application/query
  services;
- route catalog asset downloads through Resources + Providers runtime like the
  main download path.

## Invariants

- no database schema change;
- legacy Catalog ORM imports keep exact class identity;
- optimistic revisions and outbox revision semantics remain unchanged;
- Catalog never reads Provider/Resource infrastructure internals;
- release notifications remain deduplicated by (release_id, user_id);
- caller-owned transaction boundaries remain unchanged;
- Catalog does not depend on Search internals or projection state;
- no new architecture debt IDs.
