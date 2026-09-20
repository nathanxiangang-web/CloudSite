# CloudSite 1.0.0 Public Contracts

This document is the compatibility baseline for CloudSite 1.0.0. Compatible additions may be introduced in later 1.x releases. Existing contract names should not be renamed or removed without a documented deprecation path.

## 1. HTTP routes

### 1.1 Anonymous routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Service health and version |
| `POST` | `/api/auth/login` | Public-user sign-in |
| `POST` | `/api/auth/register` | Public-user registration when enabled |
| `GET` | `/api/site` | Public site configuration |
| `GET` | `/api/public/share-page` | Public share-page configuration |
| `GET` | `/api/public/share-page/image` | Public share-page image |
| `GET` | `/api/public/shares/{token}` | Share metadata |
| `POST` | `/api/public/shares/{token}/verify` | Verify a share access code |
| `GET` | `/api/public/shares/{token}/content` | Share-scoped content |
| `GET` | `/api/public/shares/{token}/download` | Single-resource share download |
| `GET` | `/api/public/shares/{token}/download/{resource_id}` | Share-scoped resource download |
| `GET` | `/s/{token}` | Share page |
| `GET` | `/s/{token}/d` | Direct single-resource share download |
| `GET` | `/s/{token}/d/{resource_id}` | Share-scoped direct download |

### 1.2 Public-user session routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/logout` | Sign out |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/auth/change-password` | Change password |
| `GET` | `/api/home` | Home-page data (popular_strategy, type_entries) |
| `GET` | `/api/browse` | All-type browse with optional type filter |
| `GET` | `/api/storage/info` | Storage display information |
| `GET` | `/api/content-roots` | Published content roots |
| `GET` | `/api/resources` | Paginated resource list |
| `GET` | `/api/resources/{resource_id}` | Resource detail |
| `GET` | `/api/resources/{resource_id}/preview` | Preview metadata |
| `GET` | `/api/resources/{resource_id}/text-preview` | Text preview |
| `GET` | `/api/resources/{resource_id}/pdf-preview` | PDF preview |
| `GET` | `/api/resources/{resource_id}/office-preview` | Office preview |
| `GET` | `/office-files/{filename}` | Guarded Office preview file |
| `GET` | `/api/folders` | Folder list |
| `GET` | `/api/folders/{folder_id}` | Folder detail |
| `GET` | `/api/search` | Search |
| `GET` | `/api/collections` | Collection list |
| `GET` | `/api/collections/{collection_id}` | Collection detail |
| `GET` | `/api/shares/{token}` | Authenticated share information |
| `GET` | `/d/{resource_id}` | Download gateway, returns HTTP 302 |
| `GET` | `/p/{resource_id}` | Binary preview gateway, returns HTTP 302 |
| `POST` | `/api/me/favorites/{resource_id}` | Add a favorite |
| `DELETE` | `/api/me/favorites/{resource_id}` | Remove a favorite |
| `GET` | `/api/me/favorites/{resource_id}` | Read favorite state |
| `GET` | `/api/me/favorites` | Favorite list |
| `POST` | `/api/me/history/{resource_id}/touch` | Record resource history |
| `GET` | `/api/me/history` | History list |
| `DELETE` | `/api/me/history` | Clear history |
| `DELETE` | `/api/me/history/{resource_id}` | Remove one history record |
| `GET` | `/api/me/playback/{resource_id}` | Read playback progress |
| `PUT` | `/api/me/playback/{resource_id}` | Save playback progress |
| `DELETE` | `/api/me/playback/{resource_id}` | Remove playback progress |
| `GET` | `/api/me/playback` | Playback list |
| `GET` | `/api/my/shares` | Current user's shares |
| `POST` | `/api/my/shares` | Create a user share |
| `PATCH` | `/api/my/shares/{token}` | Update a user share |
| `DELETE` | `/api/my/shares/{token}` | Delete a user share |
| `POST` | `/api/submissions` | Create a resource suggestion |
| `GET` | `/api/submissions/mine` | Current user's suggestions |
| `GET` | `/api/notifications` | Current user's notifications |
| `DELETE` | `/api/notifications/{notification_id}` | Remove a user notification |

### 1.3 Administrator-session routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/auth/status` | Administrator authentication status |
| `POST` | `/api/admin/auth/login` | Administrator sign-in |
| `POST` | `/api/admin/auth/logout` | Administrator sign-out |
| `GET` | `/api/admin/setup/status` | Initial setup status |
| `POST` | `/api/admin/setup/alist` | One-time AList setup |
| `GET` | `/api/admin/overview` | Administration overview |
| `GET`, `POST` | `/api/admin/users` | List or create users |
| `GET`, `PATCH`, `DELETE` | `/api/admin/users/{user_id}` | Read, update, or delete a user |
| `PATCH` | `/api/admin/users/{user_id}/status` | Enable or disable a user |
| `POST` | `/api/admin/users/{user_id}/reset-password` | Reset a password |
| `POST` | `/api/admin/downloads/diagnose` | Run download diagnostics |
| `GET` | `/api/admin/downloads/diagnostics` | Diagnostic history |
| `GET` | `/api/admin/identities/stats` | Stable-identity statistics |
| `GET` | `/api/admin/identities/candidates` | Identity candidates |
| `GET`, `PUT` | `/api/admin/alist` | Read or update AList settings |
| `POST` | `/api/admin/alist/test` | Test the AList connection |
| `GET` | `/api/admin/alist/directories` | Browse AList directories |
| `GET`, `POST` | `/api/admin/root-mappings` | List or create content roots |
| `PUT`, `DELETE` | `/api/admin/root-mappings/{mapping_id}` | Update or delete a content root |
| `POST` | `/api/admin/sync` | Start synchronization |
| `GET` | `/api/admin/sync/status` | Synchronization status |
| `POST` | `/api/admin/sync/path` | Synchronize one directory |
| `POST` | `/api/admin/sync/auto-toggle` | Change automatic synchronization |
| `POST` | `/api/admin/sync/window/run` | Run a rolling window |
| `POST` | `/api/admin/search/rebuild` | Rebuild FTS |
| `GET` | `/api/admin/index/summary` | Index summary |
| `GET` | `/api/admin/index/folders` | Indexed folder list |
| `GET` | `/api/admin/index/folders/{folder_id}` | Indexed folder detail |
| `GET` | `/api/admin/sync-runs` | Synchronization runs |
| `GET` | `/api/admin/sync-runs/{run_id}/changes` | Changes for one run |
| `GET`, `POST` | `/api/admin/collections` | List or create collections |
| `GET`, `PUT`, `DELETE` | `/api/admin/collections/{collection_id}` | Read, update, or delete a collection |
| `PUT` | `/api/admin/collections/{collection_id}/items` | Replace collection items |
| `GET`, `POST` | `/api/admin/shares` | List or create shares |
| `PATCH`, `DELETE` | `/api/admin/shares/{token}` | Update or delete a share |
| `GET`, `PUT` | `/api/admin/system` | Read or update system settings |
| `GET`, `PUT` | `/api/admin/site` | Read or update site settings |
| `POST`, `DELETE` | `/api/admin/site/share-image` | Upload or remove the share-page image |
| `GET` | `/api/admin/submissions` | Submission list |
| `GET`, `PATCH`, `DELETE` | `/api/admin/submissions/{submission_id}` | Read, update, or delete a submission |
| `GET`, `POST` | `/api/admin/notifications` | List or create notifications |
| `PATCH`, `DELETE` | `/api/admin/notifications/{notification_id}` | Update or delete a notification |

## 2. Error response shape

Errors use a stable envelope:

```json
{
  "detail": {
    "code": "ERROR_CODE",
    "message": "Human-readable message"
  }
}
```

Primary error-code families:

| Family | Examples |
|---|---|
| Authentication and sessions | `AUTH_REQUIRED`, `SESSION_INVALID`, `SESSION_REVOKED`, `SESSION_EXPIRED`, `USER_DELETED`, `USER_DISABLED`, `ADMIN_REQUIRED` |
| Shares | `SHARE_NOT_FOUND`, `SHARE_CODE_INVALID`, `SHARE_TICKET_INVALID`, `SHARE_RESOURCE_NOT_ALLOWED`, `SHARE_DOWNLOAD_LIMIT_REACHED` |
| Share images | `SHARE_IMAGE_EMPTY`, `SHARE_IMAGE_INVALID`, `SHARE_IMAGE_NOT_FOUND`, `SHARE_IMAGE_TOO_LARGE` |
| Resources and downloads | `RESOURCE_NOT_AVAILABLE`, `DOWNLOAD_RATE_LIMITED`, `RS-001` |
| Previews and folders | `PV-001`, `PV-002`, `FD-001` |
| Search | `SRCH-001`, `SRCH-002`, `SRCH-003`, `SRCH-004` |
| AList | `AL-006`, `AL-999` |
| Generic system errors | `API-001`, `VALIDATION_ERROR`, `INTERNAL_ERROR`, `HTTP_{status}` |

Responses must not expose tracebacks, internal filesystem paths, plaintext credentials, credential ciphertext, password hashes, session-token hashes, share-code hashes, provider raw URLs, or provider signatures.

## 3. Environment variables

### Stable application variables

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDSITE_SECRET_KEY` | required | Session signing and credential-encryption fallback |
| `CLOUDSITE_MASTER_KEY` | empty | Preferred independent credential-encryption key |
| `CLOUDSITE_SETUP_TOKEN` | empty | One-time initial AList setup token |
| `CLOUDSITE_DATA_DIR` | `data` | Data directory inside the application environment |
| `CLOUDSITE_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated credentialed CORS origins; `*` is rejected |
| `CLOUDSITE_TRUSTED_PROXY_CIDRS` | loopback and Docker private range | Proxies trusted to provide forwarded client addresses |
| `CLOUDSITE_SYNC_MISSING_CONFIRM_RUNS` | `2` | Independent absence confirmations required before `missing` |
| `CLOUDSITE_OFFICE_CACHE_TTL_SECONDS` | `3600` | Office-preview cache lifetime |
| `CLOUDSITE_OFFICE_CACHE_MAX_BYTES` | `209715200` | Office-preview cache size limit |

### Deployment variables

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDSITE_DATA_PATH` | `./data` | Host persistent-data directory |
| `CLOUDSITE_WEB_BIND` | `0.0.0.0` | Published Web bind address |
| `CLOUDSITE_WEB_PORT` | `3000` | Published Web port |
| `CLOUDSITE_API_IMAGE` | GHCR API image | API image repository |
| `CLOUDSITE_WEB_IMAGE` | GHCR Web image | Web image repository |
| `CLOUDSITE_IMAGE_TAG` | `v2.0.0-alpha.3` | Fixed deployment image tag |
| `CLOUDSITE_DOMAIN` | `cloud.example.com` | Traefik hostname |
| `TRAEFIK_NETWORK` | `my-servers_app-net` | Existing Traefik Docker network |
| `TRAEFIK_ENTRYPOINT` | `websecure` | Traefik entry point |
| `TRAEFIK_CERT_RESOLVER` | `myresolver` | Traefik certificate resolver |
| `API_INTERNAL_URL` | `http://api:8000` | Web-to-API internal address |
| `NEXT_PUBLIC_SITE_NAME` | `CloudSite` | Default public site name |

## 4. Persistent volume

| Host | Container | Contents |
|---|---|---|
| `${CLOUDSITE_DATA_PATH:-./data}` | `/data` | `state.db`, `index.db`, preview cache, site assets, and recovery metadata |

Never run `docker compose down -v` or delete the data directory without a verified backup.

## 5. Data ownership

`state.db` is authoritative and must be backed up. `index.db` is rebuildable but should still be included in normal backups for faster recovery.

Loss of `state.db` produces `STATE_RECOVERY_REQUIRED`. Loss of `index.db` produces `INDEX_RECOVERY`; it is not treated as a new installation.

## 6. Transfer contract

`/d/{resource_id}`, `/p/{resource_id}`, and share-download routes validate scope and return HTTP 302 to an AList-native entry. CloudSite 1.0.0 does not proxy file bodies.

## 7. Authentication contract

- Public-user authentication and administrator authentication are separate.
- The default protected site requires a valid public-user session outside the explicit anonymous allowlist.
- Disabled, deleted, expired, reset, or revoked accounts cannot continue using old sessions.
- `cloudsite_session` and `cloudsite_user_session` are HttpOnly cookies.
- The one-time setup token is not a daily administrator credential and should be removed after initial setup.

## 8. Share contract

- `/s/{token}` is the anonymous share entry.
- Optional four-digit codes are stored as HMAC hashes.
- Share tickets are short-lived and scoped to the current share.
- Supported fixed lifetimes are `5m`, `1h`, `6h`, `24h`, `7d`, and `permanent`.
- Expired or cancelled shares become inaccessible and are later removed by retention cleanup.
- Share downloads redirect to AList and never proxy file bodies through CloudSite.
