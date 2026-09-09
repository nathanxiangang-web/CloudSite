# CloudSite 1.0.0 Architecture

## System overview

```text
Browser
  -> Next.js / React
  -> FastAPI
       -> authentication and application state -> state.db
       -> browse and search index              -> index.db
       -> synchronization provider             -> AList -> storage provider
  -> HTTP 302 download or binary preview       -> AList -> storage provider
```

CloudSite is an index, policy, presentation, and redirect layer. AList remains the storage gateway, and the underlying provider remains responsible for file delivery.

## Transfer semantics

Downloads, binary previews, and share downloads use HTTP 302 redirects to an AList-native entry. CloudSite does not proxy file bodies.

| Entry | Behavior |
|---|---|
| `/d/{resource_id}` | Authorize, resolve the resource, build an AList entry, return `302` |
| `/p/{resource_id}` | Authorize, resolve the preview entry, return `302` |
| `/s/{token}/d...` | Validate the share scope, resolve a stable resource ID, return `302` |

This boundary prevents CloudSite from becoming the file-transfer bottleneck. Transfer speed and codec support depend on AList, the storage provider, the network, and the browser.

## Database ownership

### `state.db`: authoritative instance state

`state.db` contains configuration, users, sessions, encrypted AList credentials, content-root mappings, collections, shares, resource identities, operation logs, and rate-limit state. It must be backed up.

If an established instance loses `state.db`, CloudSite fails closed with `STATE_RECOVERY_REQUIRED` instead of silently creating a new identity database.

### `index.db`: rebuildable content index

`index.db` contains folders, resources, full-text search data, synchronization runs, cycles, cycle items, folder scan state, and provider synchronization state.

If `index.db` is unavailable while `state.db` is valid, CloudSite enters `INDEX_RECOVERY`. The instance identity and business data remain intact while the content index is rebuilt.

## Synchronization model

The first successful synchronization scans every enabled content root and creates the folder, resource, and FTS indexes. CloudSite then uses Rolling Full Verification for a generic AList provider:

```text
24-hour cycle = four 6-hour windows
each window verifies a subset of folders
default request spacing = randomized 5-15 seconds
absolute request ceiling = approximately 2 requests per second
```

Safety rules:

- A missing object must remain absent across two independent cycles before it becomes `missing`.
- Large path churn triggers scope-level zero-write protection.
- Cycle, window, and folder progress is persistent and resumes after restart.
- AList rate limits or access restrictions open a circuit breaker and retain unfinished work.
- Generic AList is not presented as a true delta provider.

## Stable resource identity

New resources receive random 128-bit stable IDs. A reliable rename or move preserves the ID; copies, path reuse, and ambiguous matches receive a new ID. The resolver favors a new identity over an incorrect merge.

Folder IDs may still be path-derived, and generic AList cannot identify every move or copy with complete certainty.

## Authentication boundaries

- Public user sessions and administrator sessions are separate.
- AList administrator authentication is never treated as a public user account.
- Disabled, deleted, password-reset, or revoked users lose their active sessions.
- Only the explicit public allowlist is accessible without a user session.

## Video and document previews

CloudSite relies on browser-native video decoding and does not transcode or generate HLS. MP4 with H.264/AAC is the primary compatibility target. Unsupported media falls back to download.

Office previews use a bounded local cache. PDF, text, and Markdown previews follow their dedicated guarded endpoints.
