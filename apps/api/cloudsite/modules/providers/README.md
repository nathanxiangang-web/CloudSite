# Providers Module

## Responsibility

Storage provider abstraction and the AList client gateway. This module is the
only code that talks to AList or any storage backend. It exposes a capability
model so that indexing, resources, and delivery can query what a provider
supports (streaming, range requests, thumbnail) without knowing the backend.

Core duties:
- Manage provider connections (AList instances).
- Map content roots to provider storage paths.
- Expose provider capabilities (stream, preview, delta sync, list).
- Act as the HTTP client to AList for list, detail, and download entries.
- Track per-provider sync state for delta inventory.

## Public API

- `ProviderRegistry` - list and look up configured providers.
- `ProviderCapability` - query supported operations for a provider.
- `AListClient` - low-level gateway (list, detail, download entry).
- `resolve_content_root(mapping)` - translate a content root to provider path.
- `get_download_entry(resource_id)` - build the AList 302 redirect target.

Exports live in `contracts/public.py`.

## Domain Model

- Provider (id, name, kind, base_url, status)
- Connection (id, provider_id, config, credentials_ref)
- ContentRootMapping (content_root_id, provider_id, storage_path)
- ProviderCapability (provider_id, supports_stream, supports_preview, supports_delta)
- ProviderSyncState (provider_id, last_cursor, last_scan_at)

## Database Tables

- `alist_connections` - AList instance connections and credentials.
- `content_root_mappings` - content root to provider path mapping.
- `provider_sync_state` - delta sync cursor per provider.

## Dependencies

- platform/db
- platform/http (HTTP client, retry, timeout)
- platform/security (credential decryption for provider auth)
- platform/observability

No dependency on any business module. Providers is a leaf infrastructure domain
that other modules consume.

## Events/Tasks

- Emits `provider.connected`, `provider.disconnected`, `provider.object_changed`.
- Emits `provider.capability_changed` when a provider upgrade changes support.
- No background tasks of its own; indexing drives scan orchestration.

## Security

- Provider credentials are encrypted at rest via platform/security.
- Credential decryption happens only inside this module, never exported.
- AList base URLs are validated; no arbitrary outbound HTTP.
- Download entries are signed or scoped to prevent URL tampering.
- Never log decrypted credentials.

## Failure Modes

- AList unreachable: list/detail calls return a typed ProviderUnavailable error;
  callers degrade gracefully (stale data, retry task).
- Credential rotation: connection marked stale; admin re-auth required.
- Capability mismatch: a provider claims stream but lacks range support;
  capability probe on connect detects and downgrades the flag.
- Rate limit from AList: client backs off via platform/http retry policy.

## Tests

- `tests/unit/` - capability probing, content root resolution, client parsing.
- `tests/contract/` - public API stability, AList response parsing contracts.
- Target coverage: connection lifecycle, capability detection, error mapping.

## Do Not

- Do not let other modules import AList client directly; use contracts.
- Do not store decrypted credentials in memory beyond the request scope.
- Do not hardcode AList endpoints; read from connection config.
- Do not block on provider calls in request handlers; use tasks for scans.

## Current Migration Status

Code lives in the top-level `providers/` subpackage and `alist.py`. This is
already one of the better-structured legacy areas. Migration to
`modules/providers/` is scheduled for Phase 3, early in the order because
indexing, resources, and delivery all depend on it.