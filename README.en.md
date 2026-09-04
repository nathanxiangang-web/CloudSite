# CloudSite

[简体中文](README.md) | English

[![CI](https://github.com/nathanxiangang-web/CloudSite/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nathanxiangang-web/CloudSite/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/nathanxiangang-web/CloudSite?include_prereleases&label=release)](https://github.com/nathanxiangang-web/CloudSite/releases/tag/v1.0.0-beta.1)
[![License](https://img.shields.io/github/license/nathanxiangang-web/CloudSite)](LICENSE)

**CloudSite is a self-hosted AList file browser, search, media preview, and file-sharing portal.**

CloudSite turns AList directories into a clean resource website for browsing, full-text search, image and video preview, document preview, controlled sharing, and HTTP 302 direct downloads. It is suitable for private file portals, software catalogs, media libraries, and self-hosted download sites.

> Current development and release baseline: **1.0.0-beta.1**. Live demo: [cloud.netioi.com](https://cloud.netioi.com/)

## Highlights

- Browse and search deeply nested AList directories.
- Preview images, videos, PDF, text, Markdown, and common Office documents.
- Create expiring links with optional access codes and download limits.
- Keep AList credentials encrypted on the server.
- Download through the native AList endpoint using HTTP 302 redirects; CloudSite does not proxy file bodies.
- Run with Docker Compose on `linux/amd64` or `linux/arm64`.
- Manage content roots, rolling synchronization, users, collections, shares, and diagnostics from the admin console.

## Technology

- Web: Next.js 16, React 19, TypeScript
- API: FastAPI, SQLAlchemy, SQLite
- Deployment: Docker Compose, with optional Traefik HTTPS integration

## Quick Start

Requirements: Docker Engine and the Docker Compose plugin.

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
cp .env.example .env
```

Replace `CLOUDSITE_SECRET_KEY` in `.env`, then start CloudSite:

```bash
docker compose up -d
docker compose ps
```

Open `http://SERVER_IP:3000`. The default Compose setup exposes only the Web service; the API remains on the internal Docker network and runtime data is stored in `./data`.

## Documentation

- [Installation](docs/installation.md)
- [Architecture](docs/architecture.md)
- [User guide](docs/user-guide.md)
- [Administrator guide](docs/admin-guide.md)
- [Public contracts](docs/contracts.md)
- [Recovery guide](docs/recovery-guide.md)
- [FAQ](docs/faq.md)
- [Limitations](docs/limitations.md)
- [Changelog](CHANGELOG.md)

## Release

Download CloudSite 1.0.0 Beta 1 and its offline deployment assets from the [GitHub Release](https://github.com/nathanxiangang-web/CloudSite/releases/tag/v1.0.0-beta.1).

The repository does not include AList credentials, access tokens, `.env`, databases, indexes, logs, dependency directories, or build artifacts.

## License

CloudSite is released under the [MIT License](LICENSE).
