# ADR-001: Modular Monolith

Date: 2026-09-17
Status: Accepted

## Context

CloudSite has grown from a simple AList resource viewer to a platform with 13+ business domains (identity, users, providers, resources, indexing, search, catalog, collections, shares, submissions, notifications, automation, delivery). The current flat structure (`auth.py`, `users.py`, `indexer.py`, `models.py` at top level) no longer scales:

- `models.py` is 85KB, `migrations.py` is 78KB, `sync/rolling.py` is 54KB — hotspots.
- Modules directly import each other's internals with no boundary.
- New features pile onto shared files instead of isolated modules.
- AI agents must read the entire repo to understand any single domain.

## Decision

Adopt a **Modular Monolith** architecture with explicit module boundaries:

```text
app/          — application composition (FastAPI, lifecycle, DI)
platform/     — cross-cutting infrastructure (db, http, security, tasks)
modules/      — business modules (domain + application + infrastructure + api + contracts)
plugins/      — optional plugins
```

Each module has a `contracts/public.py` that is the only import boundary for other modules.

## Alternatives considered

1. **Microservices** — rejected: too much operational overhead for current scale, single self-hosted deployment.
2. **Full rewrite** — rejected: too risky, would freeze feature development for months.
3. **Keep flat structure** — rejected: complexity is already causing coupling issues and making AI-assisted development difficult.

## Consequences

- New code must go to `modules/`, `platform/`, or `app/`.
- Dependency rules enforced by architecture tests in CI.
- Migration uses Strangler pattern — old code runs until new modules absorb it.
- `models.py` and `migrations.py` will eventually split into per-module files.
- Legacy `sync/rolling.py` is frozen; new indexing goes to `modules/indexing/`.