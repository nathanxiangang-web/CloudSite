# Module Boundaries

## Module inventory

The business implementation home is now `apps/api/cloudsite/modules/<name>/` for every module below. Legacy top-level/service/router paths, where they still exist, are compatibility edges rather than the ownership location. Current convergence notes live in [modularization-status.md](./modularization-status.md).

| Module | Responsibility | Manifest status | Implementation home |
|--------|---------------|-----------------|---------------------|
| `identity` | Stable resource ID generation, fingerprinting, migration | partial | `modules/identity/` |
| `users` | User accounts, sessions, auth, roles and user data | partial | `modules/users/` |
| `providers` | Storage provider abstraction, AList gateway, roots and capabilities | partial | `modules/providers/` |
| `resources` | Folders/files, previews, downloads and rate limits | partial | `modules/resources/` |
| `indexing` | Inventory scan, inspection, snapshot and reconcile | active | `modules/indexing/` |
| `search` | Full-text search, projection, rebuild and recovery | partial | `modules/search/` |
| `catalog` | Catalog entries, metadata, releases and publication scope | partial | `modules/catalog/` |
| `collections` | User collections, topics and seeds | partial | `modules/collections/` |
| `shares` | Share lifecycle, tickets and scope | partial | `modules/shares/` |
| `submissions` | User submissions and admin review/publish workflow | partial | `modules/submissions/` |
| `notifications` | Notification persistence and delivery-facing contracts | partial | `modules/notifications/` |
| `automation` | Parser candidates and suggestion generation/review | partial | `modules/automation/` |
| `delivery` | Delivery preparation, redirects, events and diagnostics | partial | `modules/delivery/` |
| `presentation` | Presets, theme/navigation/home blocks and revisions | partial | `modules/presentation/` |
| `setup` | First-run setup orchestration | partial | `modules/setup/` |
| `site` | Site identity/settings and public branding state | partial | `modules/site/` |

## Platform layer

| Package | Responsibility | Current code |
|---------|---------------|-------------|
| `platform/db` | Database engines, sessions, ORM base, migration registry | `database.py`, `models.py`, `migrations.py` |
| `platform/http` | Middleware, request context, exception handlers | `infrastructure/middleware.py`, `infrastructure/exception_handlers.py`, `request_context.py` |
| `platform/security` | Session tokens, crypto, credential service | `infrastructure/security.py`, `crypto.py` |
| `platform/tasks` | Task queue, worker runtime, lease, retry | `platform/tasks/` |
| `platform/observability` | Operation/audit observability boundary | `platform/observability/` |
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