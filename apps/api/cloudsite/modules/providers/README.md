# Providers Module

## Responsibility

Providers owns storage-provider configuration, root mappings, provider runtime
access, and scan-source composition. It is the boundary that prevents business
modules such as Indexing, Resources, and Delivery from depending on AList
credentials, provider ORM, or low-level transport details.

Core duties:
- Manage AList/provider connection lifecycle and encrypted credentials.
- Manage content-root to provider-path mappings.
- Expose provider information, enabled roots, runtime access, and capabilities.
- Build provider-neutral scan sources for Indexing.
- Resolve provider download/preview entries through the Providers runtime.
- Keep low-level AList construction and credential decryption inside the
  Providers boundary.

## Public Contract

Consumers should use `contracts/public.py`. Important contract groups include:

- provider/root information: `enabled_content_roots`, `enabled_root_ids`,
  `provider_info`, `provider_connected`, `public_storage_info`;
- provider runtime: `ProviderRuntimePort`, `ProviderEntry`,
  `provider_runtime`;
- indexing scan source: `ProviderScanPort`, `ProviderScanRoot`,
  `ProviderScanSource`, `enabled_provider_scan_sources`;
- connection administration and health/test/save workflows;
- root-mapping CRUD/path validation;
- provider registry/capability/sync-strategy contracts.

`AListClient` itself is **not** a cross-module public contract. The current
`GenericAListProvider` adapter and Providers application services may compose
the legacy low-level transport internally, but other modules should not import
that transport directly.

## Persistence

Providers owns:
- `alist_connections`
- `content_root_mappings`
- `provider_sync_state`

The ORM declarations live under
`modules/providers/infrastructure/models.py`; root-model exports remain
compatibility aliases where still required.

## Dependencies

- platform/db
- platform/http
- platform/security
- platform/observability

Providers should not depend on business-module internals.

## Security

- Provider credentials are encrypted at rest.
- Credential decryption stays inside Providers and is not exposed in public
  DTOs/contracts.
- Provider URLs and paths are validated before outbound operations.
- Never log decrypted credentials or secret-bearing download URLs.
- Other modules must use Providers contracts rather than importing AList
  transport or provider ORM.

## Failure Modes

- Provider unavailable: expose typed/provider-neutral runtime failures to
  callers.
- Invalid credentials or connection settings: admin test/save flow fails
  without leaking ciphertext/plaintext secrets.
- Invalid root path: root-mapping validation rejects the change.
- Scan-source construction failure: Indexing receives a provider-boundary
  failure rather than direct AList/ORM objects.

## Current Migration Status

Migration status remains `partial`, but the production ownership boundary has
reached its current stop point:

- `AListConnection`, `ContentRootMapping`, and `ProviderSyncState` ORM
  ownership is module-local;
- admin connection lifecycle, credential crypto, test/save/health operations,
  directory browsing, and root-mapping management are Providers-owned;
- production download/preview resolution is exposed through the Providers
  runtime contract;
- production inventory scanning is composed by Providers and gives Indexing
  only provider-neutral scan ports/root DTOs.

The low-level AList HTTP transport still lives in the legacy
`cloudsite.alist` surface. That location is an intentional compatibility/
internal edge at this stage, not an automatic migration task. Physically moving
it would add churn without changing the cross-module boundary because
production consumers already go through Providers contracts.

Revisit that transport only when at least one concrete need exists, such as:
- a real cross-module caller still bypassing Providers;
- replacing/supporting another storage backend;
- transport-specific testing/maintenance pain that the move materially reduces.

Until then, preserve the boundary and avoid refactoring solely to make the
folder layout look purer.
