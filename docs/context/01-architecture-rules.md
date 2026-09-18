# AI Context Pack: Architecture Rules

Purpose: the non-negotiable rules an AI agent must follow when editing
CloudSite. Violating these breaks the build (architecture tests in CI) or
causes coupling that undoes the modular monolith.

## Layer Structure

```text
apps/api/cloudsite/
  app/           - application composition (FastAPI, lifecycle, DI)
  platform/      - cross-cutting infrastructure (no business logic)
  modules/       - 13 business modules
  plugins/       - optional plugins (env-gated)
```

Dependency direction is strictly:

```text
modules -> platform
modules -> modules (via contracts only)
app -> modules, platform
platform -> (nothing in modules or app)
plugins -> platform, modules (via contracts)
```

## Rule 1: Modules Import Contracts Only

Modules may not import another module's internal implementation.

Forbidden:
```python
from cloudsite.modules.catalog.infrastructure.models import CatalogEntry
from cloudsite.modules.shares.application.services import ShareService
```

Allowed:
```python
from cloudsite.modules.catalog.contracts.public import CatalogReader
from cloudsite.modules.shares.contracts.public import ShareScope
```

Enforcement: architecture test scans modules/*/ imports and rejects any import
from modules/<other>/{domain,application,infrastructure,api}/.

## Rule 2: Router Is Thin

API routers only:
1. Parse requests.
2. Check permissions.
3. Call an application service.
4. Return the response.

Forbidden in routers:
- Multi-step SQL.
- Cross-module transaction assembly.
- State machine logic.
- Retry logic.
- Provider calls.
- Indexing logic.

Enforcement: architecture test checks that api/router.py files do not import
sqlalchemy directly or call session.commit().

## Rule 3: No cloudsite.main Dependency

No module may import from cloudsite.main.

Forbidden:
```python
from cloudsite.main import app
from cloudsite import main
```

app/api.py (or main.py) only creates FastAPI, registers routers/middleware,
manages lifecycle, and does DI. It contains no business logic.

## Rule 4: Platform Cannot Depend on Modules

The platform layer may not depend on any business module.

Forbidden:
```text
platform -> modules
platform -> catalog
platform -> shares
```

Platform provides infrastructure (db, http, security, tasks, observability,
settings) that modules consume. It must not know about business domains.


## Rule 5: Frontend Uses Feature Boundaries

Frontend is part of the CloudSite 2.0 modularization effort.

Required direction:

```text
app -> features
features -> lib/api, components/ui
features -> other features only through public entry points
components/ui -> no business features
```

Rules:

- `app/**/page.tsx` should stay thin and compose a feature view.
- Feature-specific API calls, hooks, state, components, and styles belong in `features/<name>/`.
- New business-page CSS must not be appended to `app/globals.css`.
- `app/globals.css` is a legacy hotspot and should shrink toward tokens, resets, and shared layout only.
- Shared presentational primitives belong in `components/ui/`; business-specific components remain in their feature.
- A feature must not import another feature's internal files directly. Import from that feature's public entry point.
- Large route pages should be migrated incrementally, not rewritten all at once.

Target feature shape:

```text
features/<name>/
  index.ts
  api.ts
  types.ts
  hooks/
  components/
  views/
  styles/
```

Enforcement should be added incrementally through lint/architecture checks as features migrate.

## Module Internal Structure

Each module follows the same layout:

```text
modules/<name>/
  domain/           - entities, value objects, policies, errors
  application/      - commands, queries, services (orchestrates domain + infra)
  infrastructure/   - repository, ORM models, external adapters
  api/              - router, request/response schemas
  contracts/        - public interface (what other modules may import)
  tests/            - unit and contract tests
  public/           - (some modules) stable schemas for tasks/events
  README.md         - module documentation
```

Not all modules need all directories immediately. New modules must have at
least README.md, api/, application/, infrastructure/, and tests/.

## Contracts Boundary

contracts/public.py is the only file other modules may import from. It
contains:
- Service interfaces (protocols / abstract classes).
- DTOs and value objects that cross module boundaries.
- Event schemas.
- Repository interfaces.

It must not contain implementation. It must not import from domain/,
application/, or infrastructure/ of its own module (to avoid leaking
internals through the contract).

## Event Direction

Modules communicate cross-boundary via events, not direct calls:
- A module emits events (e.g., catalog.metadata_changed).
- Consumers subscribe via the platform event bus.
- This keeps dependency direction acyclic: catalog does not import search;
  search consumes catalog's events.

## What Platform Contains

| Subsystem | Contents |
|-----------|----------|
| db | engines, sessions, unit_of_work, repository base, migrations |
| http | middleware, request context, exception handlers, retry policy |
| security | token generation, password hashing, crypto, credential service |
| tasks | task queue, worker runtime, lease, retry, registry, repository |
| observability | structured logging, metrics, tracing |
| settings | configuration loading (env-driven) |

Platform has no business logic and no knowledge of modules.

## What App Contains

| File | Role |
|------|------|
| app/api.py | FastAPI construction, router and middleware registration |
| app/lifecycle.py | startup/shutdown lifespan management |
| app/composition.py | dependency injection / service composition |

App wires modules together but contains no business logic itself.

## Enforcement

- Architecture tests in CI scan imports and reject violations.
- Code review checks router thinness and contract boundaries.
- The module README's "Do Not" section lists module-specific prohibitions.

## When to Add a New Module

1. Create modules/<name>/ with the required directories.
2. Write README.md with all 11 required sections.
3. Define contracts/public.py with the public interface.
4. Add architecture test coverage for the new module's imports.
5. Register the module's router in app/api.py.
6. Add the module to the migration strategy doc.