# Module Boundaries

## Module inventory

| Module | Responsibility | Owner | Current code location |
|--------|---------------|-------|----------------------|
| `identity` | Stable resource ID generation, fingerprinting, migration | — | `identity/` |
| `users` | User accounts, sessions, auth, admin auth | — | `auth.py`, `users.py`, `userdata.py`, `sessions.py`, `admin_auth.py` |
| `providers` | Storage provider abstraction, AList client, capabilities, delta | — | `providers/`, `alist.py`, `connection_schemas.py` |
| `resources` | Resource domain: folders, files, previews, downloads, rate limit | — | `indexer.py`, `search.py`, `preview.py`, `download.py`, `download_rate_limit.py`, `office.py` |
| `indexing` | Inventory scan, resource inspection, snapshot, reconcile | — | `sync/`, `tasks/` (new module; legacy rolling frozen) |
| `search` | Full-text search, search projection, search index recovery | — | `search.py`, `services/catalog_search*.py` |
| `catalog` | Catalog entries, metadata, follow, views | — | `services/catalog*.py`, `routers/catalog.py`, `routers/admin/catalog*.py`, `catalog_schemas.py` |
| `collections` | User collections, topics, seeds | — | `services/collections.py`, `services/collection_seeds.py`, `routers/collections.py` |
| `shares` | Share links, tickets, scope, share page | — | `shares/`, `routers/shares.py` |
| `submissions` | User submissions, admin review | — | `services/submissions.py`, `routers/submissions.py` |
| `notifications` | Notification channels | — | `services/notifications.py`, `routers/notifications.py` |
| `automation` | Automation rules, suggestion engine, parser candidates | — | `services/suggestion_*.py`, `services/parser_candidate*.py`, `routers/admin/automation.py`, `routers/admin/parser_candidates.py` |
| `delivery` | Delivery preparation, redirect | — | `services/delivery.py`, `routers/delivery.py`, `delivery_schemas.py` |
| `presentation` | Site presentation presets, theme/navigation/home blocks, revisions and rollback | — | `modules/presentation/`, legacy `services/presentation.py`, `routers/admin/presentation.py` |
| `setup` | First-run setup workflow progress and cross-module onboarding orchestration | — | `modules/setup/`, `routers/admin/setup.py` |
| `site` | Site identity/settings, registration policy, Home limits, and share-page branding state | — | `modules/site/`, compatibility `site.py`, `routers/admin/site.py` |

## Platform layer

| Package | Responsibility | Current code |
|---------|---------------|-------------|
| `platform/db` | Database engines, sessions, ORM base, migration registry | `database.py`, `models.py`, `migrations.py` |
| `platform/http` | Middleware, request context, exception handlers | `infrastructure/middleware.py`, `infrastructure/exception_handlers.py`, `request_context.py` |
| `platform/security` | Session tokens, crypto, credential service | `infrastructure/security.py`, `crypto.py` |
| `platform/tasks` | Task queue, worker runtime, lease, retry | `tasks/` (to be expanded in B2) |
| `platform/observability` | Structured logging, metrics, tracing | (new) |
| `platform/settings` | Configuration | `config.py` |

## App layer

| File | Responsibility | Current code |
|------|---------------|-------------|
| `app/api.py` | FastAPI construction, router registration | `main.py` (route registration section) |
| `app/lifecycle.py` | Startup/shutdown lifespan | `infrastructure/lifespan.py` |
| `app/composition.py` | Dependency injection, service composition | `main.py` (DI section) |

## Module contract requirements

Each module must expose a public contract:

```python
# modules/<name>/contracts/public.py
# This is the ONLY file other modules may import from.
```

Contracts contain:
- Protocol/ABC interfaces for services
- Pydantic models for cross-module data transfer
- Re-exported domain types that are part of the public API

Contracts must NOT contain:
- ORM models (those are infrastructure)
- Repository implementations
- Service implementations
- Router definitions

## Module README standard

Every module must have a `README.md` with:

```markdown
# <Module Name>

## Responsibility
## Public API
## Domain Model
## Database Tables
## Dependencies
## Events / Tasks
## Security
## Failure Modes
## Tests
## Do Not
## Current Migration Status
```