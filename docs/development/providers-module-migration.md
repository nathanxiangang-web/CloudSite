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

Status: implemented in this change.

Providers now exposes `provider_runtime(session)` through
`modules/providers/contracts/public.py`. The returned runtime port resolves an
enabled content root to its enabled connection, decrypts credentials inside the
Providers boundary, opens the AList client, and exposes only provider operations:

- `download_entry(root_mapping_id, path)`;
- `preview_entry(root_mapping_id, path)`.

Callers receive a persistence-neutral `ProviderEntry`; connection ORM objects
and decrypted credentials never leave Providers.

Missing/disabled roots or connections fail closed with
`ProviderUnavailableError`. Provider/client failures are normalized into
`ProviderAccessError.category` values such as `unreachable`,
`authentication`, `metadata`, `configuration`, and `credentials` without
leaking backend-specific details. Both download and preview operations return the
same persistence-neutral `ProviderEntry` shape with URL, host, base path, and
signature presence.

This is the prerequisite for Resources R4b: preview/cache preparation can now
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
