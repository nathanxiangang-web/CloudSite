# Resources Module

## Responsibility

The resource domain: folders, files, previews, downloads, download rate
limiting, and office document handling. This module models the tree a user
browses and the actions they take on a resource. It does not own storage; it
delegates to providers for the actual bytes and to identity for stable IDs.

Core duties:
- Folder browse and tree navigation.
- Resource detail retrieval (metadata, size, type).
- Preview resolution (thumbnail, office, media).
- Download redirect (302 to AList entry, never proxy bytes).
- Per-user and per-IP download rate limiting.
- Office document preview adapter (WPS / OnlyOffice integration points).

## Public API

- `browse_folder(folder_id)` - list children of a folder.
- `get_resource(resource_id)` - resource detail.
- `resolve_preview(resource_id)` - preview entry for 302 redirect.
- `resolve_download(resource_id)` - download entry for 302 redirect.
- `check_rate_limit(user, ip)` - rate limit gate before download.

Exports live in `contracts/public.py`.

## Domain Model

- Folder (folder_id, name, parent_id, provider_id, object_id)
- Resource (resource_id, folder_id, name, size, mime_type, modified_at)
- ResourceFile (resource_id, storage_path, checksum)
- Preview (resource_id, preview_kind, preview_entry)
- DownloadRateLimit (key, window, count, reset_at)

## Database Tables

- `folders` - folder tree nodes.
- `resources` - file resource records.
- `download_rate_limits` - rate limit counters.

## Dependencies

- platform/db
- platform/http (request context, rate limit middleware)
- modules/providers (via contracts) - for preview and download entries.
- modules/identity (via contracts) - to resolve stable resource IDs.

## Events/Tasks

- Emits `resource.viewed`, `resource.downloaded`, `resource.previewed`.
- Download events are consumed by delivery for tracking.
- Rate limit cleanup is a lazy TTL sweep, not a scheduled task.

## Security

- Download and preview require an authenticated session (or valid share token
  via the shares module, checked at the router).
- Rate limiting prevents abuse; limits are per-user and per-IP.
- Office preview tokens are short-lived and scoped to one resource.
- Never expose internal storage paths in API responses.

## Failure Modes

- Provider returns 404 for a resource: return a typed ResourceGone error;
  identity may reconcile on next scan.
- Rate limit exceeded: return 429 with Retry-After header.
- Preview unsupported for mime type: return a null preview entry, client falls
  back to download.
- Office adapter unavailable: degrade to download-only.

## Tests

- `tests/unit/` - rate limit window logic, preview kind selection.
- `tests/contract/` - public API stability.
- Target coverage: browse, detail, preview fallback, rate limit enforcement.

## Do Not

- Do not proxy file bytes through the API; always 302 to AList.
- Do not store provider-specific paths in API responses.
- Do not depend on modules/catalog or modules/shares.
- Do not implement scan logic here; that belongs to indexing.

## Current Migration Status

Migration status: partial. `Folder`, `Resource`, and `DownloadRateLimit` ORM declarations are owned by `modules/resources/infrastructure/models.py`; `cloudsite.models` remains a compatibility re-export. Indexing reconciliation persists through `ResourceInventoryPort` and the Resources-owned `SqlAlchemyResourceInventoryRepository`. Resource/folder list and detail queries now run through Resources-owned query services/repositories. The legacy resources router is now ORM-free. Preview endpoints load a persistence-neutral internal preview DTO through Resources, and preview/cache provider access now uses the Providers public runtime contract. The preview router is ORM-free and credentials/AList clients stay inside Providers. Preview/office implementation is now module-owned under Resources infrastructure; top-level `cloudsite.preview` / `cloudsite.office` are compatibility-only facades. Download lookup now uses a Resources-owned internal DTO and the download router is ORM-free; provider entry resolution flows through the Providers runtime contract. Persistent download rate limiting is now Resources-owned and exported through the Resources contract; Delivery and the top-level legacy module are compatibility facades only. Publication-scope composition and the top-level download compatibility facade remain transitional.

`indexer.py` remains a legacy mixed-responsibility surface: scan orchestration belongs to Indexing, while authoritative Folder/Resource persistence belongs to Resources.
## Admin Index Views

Resources now exposes dedicated persistence-neutral admin index views for
active Folder/Resource counts, indexed folder listings with storage paths, and
folder detail with direct active-resource counts. These views are separate from
the public browsing DTOs so admin-only path/status metadata does not leak into
the public resource contract.

## Delivery Diagnostic View

Resources exposes a narrow `DiagnosticResourceView` for Delivery diagnostics.
It includes the internal storage path and current resource state required to
probe delivery, but is not serialized by public Resources endpoints. This keeps
diagnostic storage-path access explicit and avoids reusing Catalog/public DTOs.
