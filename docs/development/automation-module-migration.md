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

Next:

- move `CatalogSuggestion` ORM ownership into Automation;
- use Resources contracts for suggestion source-file input;
- use Catalog contracts for entry/release/asset lookup and approved mutations;
- move suggestion revision/application helpers out of legacy services;
- preserve the hard rule that suggestions are never auto-applied.

Completing A5b should reduce `module_legacy_import` to zero.

## Invariants

- no parser-candidate schema change;
- legacy parser/task imports keep exact identity;
- no Automation import of Resource/Sync ORM internals;
- deterministic parser output remains byte-for-byte equivalent for the same
  input and parser version;
- no automatic suggestion application;
- no new architecture debt IDs.
