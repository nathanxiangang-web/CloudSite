# Changelog

This changelog starts from the CloudSite 1.0.0 stable baseline.

## [1.0.0] - 2026-09-07

CloudSite 1.0.0 establishes the stable self-hosted AList resource portal baseline.

### Added

- A Next.js and FastAPI resource portal for software, images, video, documents, and general files.
- Configurable content roots, full-text search, nested browsing, curated collections, and stable resource identities.
- Browser-native media playback plus image, PDF, text, Markdown, and Office previews.
- Separate public-user and administrator authentication systems.
- User favorites, browsing history, playback progress, personal shares, and email-based resource suggestions.
- Expiring shares with optional four-digit access codes, scoped tickets, status controls, counters, and download limits.
- AList-native HTTP 302 download and binary-preview gateways without file-body proxying.
- Initial full indexing followed by rolling full verification with persistent cycles and windows.
- Manual single-directory synchronization with bounded scope and graceful cancellation.
- Provider capability reporting and conservative strategy selection.
- Online, Traefik, and offline Docker Compose deployment paths for `linux/amd64` and `linux/arm64`.
- Consistent SQLite online backups, verification, protected restore, and rollback copies.
- Responsive public and administration interfaces with light and dark themes.

### Safety and reliability

- Disabled content roots are excluded from browse, search, details, previews, downloads, and collection output.
- Missing objects require confirmation across independent cycles.
- Suspicious large-scale path churn triggers zero-write scope protection.
- Stable identity resolution preserves reliable renames and moves while rejecting ambiguous merges.
- Session invalidation covers account disablement, deletion, password reset, logout, and expiry.
- Download limits use persistent, atomic state and trusted-proxy-aware client addresses.
- Production Compose requires an explicit secret key and passes the one-time setup token to API.
- Credential encryption uses a dedicated master key when configured and fails closed when the saved credential cannot be decrypted.

### Public contract

- The documented 1.0 URL routes, error codes, environment variables, data ownership, authentication boundaries, share behavior, and HTTP 302 transfer semantics form the compatibility baseline.
- Compatible additions may be introduced in later 1.x releases. Existing 1.0 contract names are not removed or renamed without a deprecation path.

[1.0.0]: https://github.com/nathanxiangang-web/CloudSite/releases/tag/v1.0.0
