# CloudSite

[![CI](https://github.com/nathanxiangang-web/CloudSite/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nathanxiangang-web/CloudSite/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/nathanxiangang-web/CloudSite?label=release)](https://github.com/nathanxiangang-web/CloudSite/releases/tag/v1.0.0)
[![License](https://img.shields.io/github/license/nathanxiangang-web/CloudSite)](LICENSE)

**CloudSite is a self-hosted AList-powered portal for browsing, searching, previewing, organizing, and sharing cloud-drive resources.**

It turns selected AList directories into a clean resource website with user accounts, media and document previews, curated collections, controlled sharing, and HTTP 302 direct downloads. CloudSite does not proxy file bodies: AList and the underlying storage provider remain responsible for file delivery.

> Current stable baseline: **CloudSite 1.0.0**
> Live site: [cloud.netioi.com](https://cloud.netioi.com/)

<p align="center">
  <img src="docs/assets/cloudsite-home.webp" alt="CloudSite home page" width="80%">
</p>

## Highlights

- Browse and search deeply nested AList directories.
- Organize software, images, videos, documents, and general files through configurable content roots.
- Preview images, browser-compatible video, PDF, text, Markdown, and common Office documents.
- Keep resource links stable across reliable rename and move operations.
- Create expiring shares with optional four-digit access codes and download limits.
- Manage users, content roots, collections, shares, site settings, synchronization, and diagnostics from the administration console.
- Protect AList credentials with server-side encryption.
- Run on `linux/amd64` and `linux/arm64` with Docker Compose.
- Use rolling full verification after the initial index without presenting generic AList as a true delta source.

## Technology

- Web: Next.js 16, React 19, TypeScript
- API: FastAPI, SQLAlchemy, SQLite
- Deployment: Docker Compose, with optional Traefik HTTPS integration

## Quick start

Requirements: Docker Engine and the Docker Compose plugin. Node.js and Python are not required on the server.

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
cp .env.example .env
```

Edit `.env` and replace `CLOUDSITE_SECRET_KEY` with a long random value. Set `CLOUDSITE_SETUP_TOKEN` for the initial AList configuration flow, then start the fixed 1.0.0 images:

```bash
docker compose up -d --wait
docker compose ps
curl -fsS http://127.0.0.1:3000/api/health
```

Open `http://SERVER_IP:3000`. The default Compose file exposes only the Web service; the API stays on the internal Docker network, and persistent data is stored in `./data`.

After the initial configuration is complete, remove `CLOUDSITE_SETUP_TOKEN` from `.env` and restart the services. Keep `CLOUDSITE_SECRET_KEY` and `CLOUDSITE_MASTER_KEY` stable after credentials have been saved, otherwise the stored AList password cannot be decrypted.

## Documentation

- [Installation](docs/installation.md)
- [Architecture](docs/architecture.md)
- [User guide](docs/user-guide.md)
- [Administrator guide](docs/admin-guide.md)
- [Public contracts](docs/contracts.md)
- [Deployment, upgrade, and backup](docs/deployment-upgrade-backup.md)
- [Offline installation](docs/offline-installation.md)
- [Operations and disaster recovery](docs/operations-disaster-recovery.md)
- [Recovery guide](docs/recovery-guide.md)
- [FAQ](docs/faq.md)
- [Limitations](docs/limitations.md)
- [Changelog](CHANGELOG.md)

## Download behavior

CloudSite validates the request and redirects the browser to an AList-native entry:

```text
Browser -> CloudSite authorization -> AList entry -> HTTP 302 -> storage provider
```

The `/d/{resource_id}`, `/p/{resource_id}`, and share-download routes do not stream file bodies through CloudSite. Transfer speed and codec compatibility therefore depend on AList, the storage provider, the network, and the browser.

## Development

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

The development Compose file exposes Web on port `3000` and API on port `8000`.

Run the primary checks before submitting changes:

```bash
docker compose -f docker-compose.dev.yml run --rm api pytest
docker compose -f docker-compose.dev.yml run --rm web npm run lint
docker compose -f docker-compose.dev.yml run --rm web npm run typecheck
docker compose -f docker-compose.dev.yml run --rm web npm run build
docker compose config
docker compose -f docker-compose.traefik.yml config
```

## Security and data

The repository does not include AList credentials, access tokens, `.env`, databases, indexes, logs, dependency directories, or build artifacts.

- `state.db` contains instance identity, users, encrypted credentials, settings, collections, and shares. It must be backed up.
- `index.db` contains the rebuildable resource index and synchronization state.
- Never run `docker compose down -v` against a production instance.
- Back up before every upgrade and verify that the backup can be restored.

See [Public contracts](docs/contracts.md) and [Operations and disaster recovery](docs/operations-disaster-recovery.md) for the 1.0.0 guarantees and operational boundaries.

## Release

Download CloudSite 1.0.0 and its offline deployment assets from the [v1.0.0 release](https://github.com/nathanxiangang-web/CloudSite/releases/tag/v1.0.0).

## License

CloudSite is released under the [MIT License](LICENSE).
