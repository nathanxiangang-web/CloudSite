# CloudSite 2.0 Architecture

## System overview

```text
Browser
  -> Next.js / React
  -> FastAPI (Modular Monolith)
       -> app/          — application composition
       -> platform/     — cross-cutting infrastructure
       -> modules/      — business modules (domain + application + infrastructure + api)
       -> plugins/      — optional plugins (AI, cloud download, ...)
       -> state.db      — authoritative instance state
       -> index.db      — rebuildable content index
       -> AList         — storage provider gateway
  -> HTTP 302 download or binary preview -> AList -> storage provider
```

CloudSite is an index, policy, presentation, and redirect layer. AList remains the storage gateway, and the underlying provider remains responsible for file delivery.

## Layer structure

```text
apps/api/cloudsite/
├── app/                     # Application layer
│   ├── api.py               # FastAPI construction + router registration
│   ├── lifecycle.py         # Startup/shutdown lifespan
│   └── composition.py       # Dependency injection / service composition
│
├── platform/                # Cross-cutting infrastructure (no business logic)
│   ├── db/                  # Database engines, sessions, migrations
│   ├── http/                # Middleware, request context, exception handlers
│   ├── security/            # Session tokens, crypto, credential service
│   ├── tasks/               # Task queue, worker runtime, lease, retry
│   ├── observability/       # Structured logging, metrics, tracing
│   └── settings/            # Configuration
│
├── modules/                 # Business modules
│   ├── identity/            # Stable resource identity
│   ├── users/               # User accounts, sessions, auth
│   ├── providers/           # Storage provider abstraction (AList, capabilities)
│   ├── resources/           # Resource domain (folders, files, previews, downloads)
│   ├── indexing/            # Inventory scan, resource inspection, snapshot
│   ├── search/              # Full-text search, search projection
│   ├── catalog/             # Catalog entries, metadata, follow
│   ├── collections/         # User collections, topics
│   ├── shares/              # Share links, tickets, scope
│   ├── submissions/         # User submissions, admin review
│   ├── notifications/       # Notification channels
│   ├── automation/          # Automation rules, suggestion engine
│   └── delivery/            # Delivery preparation, redirect
│
└── plugins/                 # Optional plugins (env-gated loading)
    ├── base.py
    ├── registry.py
    └── ai/                  # AI completion, cloud download
```

## Dependency rules

1. **Modules → Contracts only**: modules may not import another module's internal implementation. Use `modules/<name>/contracts/public.py` as the import boundary.
2. **Router is thin**: API routers only parse requests, check permissions, call application services, and return responses. No multi-step SQL, cross-module transaction assembly, state machines, retry logic, or provider calls in routers.
3. **No `cloudsite.main` dependency**: no module may import from `cloudsite.main`. `main.py` only creates FastAPI, registers routers/middleware, and manages lifecycle.
4. **Platform → no modules**: the platform layer may not depend on any business module. Dependency direction is `modules → platform` only.

See [development/dependency-rules.md](development/dependency-rules.md) for enforcement details.

## Module structure (target)

Each module follows the same internal layout:

```text
modules/<name>/
├── domain/              # Entities, value objects, policies, errors
├── application/         # Commands, queries, services (orchestrates domain + infra)
├── infrastructure/     # Repository, ORM models, external adapters
├── api/                 # Router, request/response schemas
├── contracts/           # Public interface (what other modules may import)
├── tests/               # Module-level tests
└── README.md            # Module documentation
```

Not all modules need all directories immediately. New modules must have at least `README.md`, `api/`, `application/`, `infrastructure/`, and `tests/`.

## Current-to-target migration

CloudSite uses Strangler Migration: old code continues to run while new modules承接 new paths. Legacy code is frozen (no new 2.0 logic) and gradually replaced.

See [development/migration-strategy.md](development/migration-strategy.md) for the module-by-module mapping.

## Transfer semantics

Downloads, binary previews, and share downloads use HTTP 302 redirects to an AList-native entry. CloudSite does not proxy file bodies.

| Entry | Behavior |
|---|---|
| `/d/{resource_id}` | Authorize, resolve the resource, build an AList entry, return `302` |
| `/p/{resource_id}` | Authorize, resolve the preview entry, return `302` |
| `/s/{token}/d...` | Validate the share scope, resolve a stable resource ID, return `302` |

## Database ownership

### `state.db`: authoritative instance state

Contains configuration, users, sessions, encrypted AList credentials, content-root mappings, collections, shares, resource identities, operation logs, and rate-limit state. Must be backed up.

If an established instance loses `state.db`, CloudSite fails closed with `STATE_RECOVERY_REQUIRED`.

### `index.db`: rebuildable content index

Contains folders, resources, full-text search data, synchronization runs, cycles, cycle items, folder scan state, and provider synchronization state.

If `index.db` is unavailable while `state.db` is valid, CloudSite enters `INDEX_RECOVERY`.

## Authentication boundaries

- Public user sessions: 7-day cookie, `cloudsite_user_session`.
- Admin sessions: 7-day cookie, `cloudsite_admin_session`.
- AList administrator authentication is never treated as a public user account.
- Disabled, deleted, password-reset, or revoked users lose active sessions.
- Only the explicit public allowlist is accessible without a user session.

## Synchronization model (legacy)

The 1.x Rolling Full Verification remains as a legacy compatibility path. New 2.0 indexing uses Inventory Scan + Resource Inspection (see `modules/indexing/`).

Legacy rolling:

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

**No new 2.0 logic may be added to `sync/rolling.py`.** New indexing code goes to `modules/indexing/`.
