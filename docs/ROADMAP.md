# CloudSite Roadmap

This public roadmap summarizes the direction of CloudSite without exposing internal implementation plans. It is a planning document, not a release commitment.

## Released

### v1.0.0 — Stable baseline

- AList-powered resource portal with browse, search, preview, sharing and direct-download flows.
- User accounts and administration console.
- Stable resource identities and local search/index state.
- Docker Compose deployment for `linux/amd64` and `linux/arm64`.
- Backup, recovery, diagnostics and compatibility checks.

## Current development line

### v2.0.0-alpha.x — Resource platform evolution

The 2.0 development line is experimental and may change before the stable release. Current work focuses on evolving CloudSite from a file-oriented portal into a resource-oriented platform while preserving the proven self-hosted deployment model.

Public areas of active development include:

- richer resource catalog and metadata workflows;
- publication scope, quality controls and submission workflows;
- roles, API access and multi-connection management;
- automation and optional AI-assisted content workflows;
- stronger module boundaries and background-job architecture;
- indexing and synchronization improvements for larger resource libraries;
- frontend maintainability and critical-path end-to-end testing.

## Longer-term direction

Future work may include additional storage/provider integrations, a more stable external API surface, plugin extensibility, stronger observability and larger-scale deployment options. These will be driven by demonstrated user needs rather than added only for architectural complexity.

## Release policy

- `v1.x` is the stable compatibility line.
- `alpha`, `beta` and `rc` releases are prereleases and are intended for testing and evaluation.
- Stable releases are published only after compatibility, migration, backup/restore and deployment checks pass.

For installation and upgrade instructions, see [Installation](installation.md) and [Deployment, upgrade, and backup](deployment-upgrade-backup.md).
