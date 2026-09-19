# Providers Module Migration

Providers owns storage connection configuration, content-root mapping, provider
capabilities, and provider sync state. It is a prerequisite boundary for clean
Resources preview/download composition.

## P1 — ORM ownership

Status: implemented in this change.

The following ORM declarations move from `cloudsite.models` to
`modules/providers/infrastructure/models.py`:

- `AListConnection` -> `alist_connections`;
- `ContentRootMapping` -> `content_root_mappings`;
- `ProviderSyncState` -> `provider_sync_state`.

`cloudsite.models` remains an exact compatibility re-export, so existing
callers, database metadata, schema, and migration history stay unchanged.

The existing Providers application service now imports the module-owned
`AListConnection`, removing one tracked `module_legacy_import` debt ID.

Architecture debt ratchets from 85 to 84:

- module legacy imports: 24 -> 23;
- router ORM imports: 61;
- cross-module internal imports: 0.

## P2 — runtime provider gateway

Next, add a Providers-owned runtime gateway that resolves an enabled
`ContentRootMapping` to provider operations while keeping credentials and
decryption inside Providers.

The public boundary should expose provider operations or persistence-neutral
results, not `AListConnection` ORM instances and never decrypted credentials.

This is the prerequisite for Resources R4b: preview/cache preparation can then
depend only on `modules/providers/contracts` instead of legacy
`services.connections`.

## P3 — connection CRUD and compatibility records

Move admin connection CRUD, compatibility records, and remaining provider
configuration queries behind Providers application/repository boundaries.

## Invariants

Every slice preserves:

- table names and shared StateBase/IndexBase metadata;
- existing connection IDs and content-root mapping IDs;
- encrypted credential storage;
- provider type/capability fields;
- sync cursor/state compatibility;
- no new architecture-debt IDs.
