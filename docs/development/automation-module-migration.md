# Automation Module Migration

Automation owns deterministic parser logic, durable parser-candidate workflow,
suggestion generation/review, and automation-only advisory state. Automation
output remains advisory until an editor applies it.

## A5a — parser core ownership

Status: implemented.

### Parser domain

The deterministic resource-name parser now lives in:

```text
modules/automation/domain/resource_name_parser.py
```

The legacy `cloudsite.services.resource_name_parser` module is an
implementation-free compatibility facade and re-exports the exact parser
classes/functions/constants.

### Parser candidate persistence

`ParserCandidateTask` now lives in:

```text
modules/automation/infrastructure/models.py
```

`cloudsite.models.ParserCandidateTask` re-exports the exact same SQLAlchemy
class. No schema migration is intended.

### Resource input boundary

Automation no longer reads Resources ORM directly. Parser execution uses:

```text
modules/resources/contracts/public.py
  -> resource_queries(index).parser_resource(...)
  -> ParserResourceView
```

The view exposes only the fields consumed by the deterministic parser:

- id
- name
- path
- extension
- mime_type
- status

### Sync-change seeding boundary

Automation no longer imports `SyncRun` or `SyncChange` ORM.

Indexing exposes a read-only parser-seeding contract:

```text
modules/indexing/contracts/public.py
  -> parser_seed_run(...)
  -> parser_seed_changes(...)
```

The implementation performs parameterized reads over the legacy sync tables and
returns persistence-neutral run/change views. Sync-table ownership is not moved
in A5a.

### Preserved behavior

A5a does not change:

- parser version or parsing algorithm;
- parser input fingerprint fields;
- candidate transition graph;
- retry count/limit behavior;
- batch ordering and bounds;
- restart recovery behavior;
- seeding skipped/error counters;
- caller-owned transaction boundaries.

### Architecture debt

A5a removes eight tracked Automation parser debt IDs.

```text
67 -> 59
module_legacy_import: 12 -> 4
router_orm_import: 55
```

The remaining four module debt IDs are all in:

- `suggestion_generator.py`
- `suggestion_review.py`

## A5b — suggestion core ownership

Status: implemented.

### Suggestion persistence

`CatalogSuggestion` now lives in:

```text
modules/automation/infrastructure/models.py
```

`cloudsite.models.CatalogSuggestion` remains an exact compatibility re-export.
No schema migration is intended.

### Generation boundary

Suggestion generation no longer imports Resource or Catalog ORM.

Resources exposes `SuggestionResourceView` and bounded active-resource queries
through `modules/resources/contracts/public.py`.

Catalog exposes a persistence-neutral suggestion context containing only the
binding and duplicate-candidate fields required for classification.

The deterministic parser is reused directly from Automation domain code.

### Review/apply boundary

Automation continues to own suggestion lifecycle state:

```text
pending -> reviewed/applied/rejected
```

Approved Catalog mutations execute through
`modules/catalog/contracts/public.py`. The Catalog bridge owns:

- create entry/release/asset operations;
- location attachment;
- archive/disable revert operations;
- latest revision lookup;
- revision list projection into persistence-neutral DTOs.

Automation never imports Catalog ORM or Catalog legacy services.

### Architecture debt

A5b removes the final four tracked module legacy-import IDs.

```text
59 -> 55
module_legacy_import: 4 -> 0
router_orm_import: 55
```

At this point all remaining tracked architecture debt is legacy router-level
ORM/database ownership.

## Next — router boundary migration

The next phase should thin routers by domain cluster rather than reopen module
internals. Priority clusters:

1. Catalog/public Catalog routes, including asset download composition;
2. Automation/quality admin routes;
3. Providers/content-root administration;
4. Shares/collections/submissions;
5. site/system/health/diagnostics surfaces.

Each router slice should move SQL/query construction into the owning module,
preserve response/error contracts, and ratchet `router_orm_import` downward.

## Invariants

- no parser-candidate schema change;
- legacy parser/task imports keep exact identity;
- no Automation import of Resource/Sync ORM internals;
- deterministic parser output remains byte-for-byte equivalent for the same
  input and parser version;
- no automatic suggestion application;
- no new architecture debt IDs.
