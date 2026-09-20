# AI Context Pack: Project Overview

Purpose: give an AI agent enough context to work on any CloudSite task without
reading the entire repo. This file is the entry point; the other context files
drill into specific areas.

## What CloudSite Is

CloudSite is an index, policy, presentation, and redirect layer over AList
storage. It does not store file bytes. It stores metadata, catalog entries,
user accounts, shares, and a search index. Downloads and previews are HTTP 302
redirects to AList-native entries.

## System Shape

```text
Browser
  -> Next.js / React (frontend)
  -> FastAPI (Modular Monolith, Python)
       -> app/          - application composition (FastAPI, lifecycle, DI)
       -> platform/     - cross-cutting infrastructure (no business logic)
       -> modules/      - 13 business modules
       -> plugins/      - optional plugins (AI, cloud download)
       -> state.db      - authoritative instance state
       -> index.db      - rebuildable content index
       -> AList         - storage provider gateway
  -> HTTP 302 download or binary preview -> AList -> storage provider
```

## The 13 Modules

| Module | Responsibility |
|--------|---------------|
| identity | Stable resource ID generation and fingerprinting |
| users | Accounts, sessions, auth, admin auth |
| providers | Storage provider abstraction, AList gateway, capabilities |
| resources | Folders, files, previews, downloads, rate limiting |
| indexing | Inventory scan, inspection, snapshot reconciliation |
| search | Full-text search, projection, index recovery |
| catalog | Catalog entries, metadata, releases, follow |
| collections | User collections, topics, seeds |
| shares | Share links, tickets, scope, share page |
| submissions | User submissions, admin review workflow |
| notifications | Notification channels (in-app, webhook) |
| automation | Suggestion engine, parser candidates, automation rules |
| delivery | Delivery preparation, download redirect, tracking |

## Platform Layer

| Subsystem | Responsibility |
|-----------|---------------|
| db | Engines, sessions, unit of work, migrations, repository base |
| http | Middleware, request context, exception handlers, retry |
| security | Session tokens, crypto, credential service, password hashing |
| tasks | Task queue, worker runtime, lease, retry, registry |
| observability | Structured logging, metrics, tracing |
| settings | Configuration (env-driven) |

## Two Databases

- **state.db**: authoritative. All business tables (users, resources, catalog,
  shares, etc.). Migrated, never rebuilt. Loss is data loss.
- **index.db**: rebuildable. FTS5 search index and projection state. Can be
  dropped and rebuilt from state.db with no data loss.

## Transfer Semantics

CloudSite never proxies file bodies. All downloads and previews are 302
redirects to AList:

| Entry | Behavior |
|-------|----------|
| /d/{resource_id} | Authorize, resolve resource, build AList entry, 302 |
| /p/{resource_id} | Authorize, resolve preview entry, 302 |
| /s/{token}/d... | Validate share scope, resolve stable ID, 302 |

## Migration State

CloudSite is mid-migration from a flat structure to the modular monolith
(ADR-001). The migration uses the Strangler pattern: old code runs while new
modules absorb new paths. Legacy code is frozen (no new 2.0 logic).

- Phase 1 (current): boundaries defined, architecture docs and tests in place.
- Phase 2: new code (tasks, indexing, repositories) goes to new structure.
- Phase 3: gradual module-by-module move from flat to modules/.
- Phase 4: legacy cleanup (delete sync/rolling.py, split models.py).

Module move order: identity -> users -> providers -> shares -> collections ->
catalog -> search -> resources -> indexing -> automation -> delivery ->
notifications -> submissions.

## Key Files

| File | Role |
|------|------|
| docs/architecture.md | Full architecture doc |
| docs/development/dependency-rules.md | Import and layer rules |
| docs/development/migration-strategy.md | Migration plan and mapping |
| docs/adr/ | Architecture Decision Records |
| docs/context/ | This AI Context Pack |
| apps/api/cloudsite/modules/*/README.md | Per-module documentation |

## How to Navigate

1. Read this file for the big picture.
2. Read 01-architecture-rules.md before touching module boundaries.
3. Read 02-data-model-map.md before touching database tables.
4. Read 03-api-contract-map.md before touching API endpoints.
5. Read 04-task-system.md before touching background work.
6. Read 05-indexing.md before touching scan or sync logic.
7. Read the relevant module's README.md for module-specific detail.

## Conventions

- Python, snake_case files, PascalCase classes.
- Pure ASCII in documentation.
- No emojis in code or docs.
- Modules import contracts only, never another module's internals.
- Routers are thin: parse, check perms, call service, return.
- No module imports from cloudsite.main.
- Platform never depends on modules.

## Stack

- Backend: FastAPI (Python), SQLAlchemy, SQLite/Postgres, FTS5.
- Frontend: Next.js / React.
- Storage gateway: AList.
- Deployment: single self-hosted binary via Docker Compose.
- AI: optional plugin (plugins/ai), env-gated.