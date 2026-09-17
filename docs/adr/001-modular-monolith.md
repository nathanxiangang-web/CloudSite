# ADR-001: Modular Monolith

Date: 2026-09-17
Status: Accepted
Supersedes: none

## Context

CloudSite grew from a simple AList resource viewer into a platform with 13+
business domains. The original flat structure (`auth.py`, `users.py`,
`indexer.py`, `models.py` at the top level) no longer scales:

- `models.py` is 85KB, `migrations.py` is 78KB, `sync/rolling.py` is 54KB.
- Modules import each other's internals with no boundary.
- New features pile onto shared files instead of isolated modules.
- AI agents must read the entire repo to understand any single domain.

## Decision

Adopt a Modular Monolith architecture with explicit module boundaries:

```text
app/          - application composition (FastAPI, lifecycle, DI)
platform/     - cross-cutting infrastructure (db, http, security, tasks)
modules/      - business modules (domain + application + infra + api + contracts)
plugins/      - optional plugins (AI, cloud download)
```

Each module has a `contracts/public.py` that is the only import boundary for
other modules. Dependency rules:

1. Modules import contracts only, never another module's internals.
2. Routers are thin: parse, check perms, call service, return.
3. No module imports from `cloudsite.main`.
4. Platform never depends on modules; direction is modules -> platform only.

## Alternatives Considered

1. **Microservices** - rejected: too much operational overhead for current
   scale and a single self-hosted deployment. Network boundaries not justified
   by team size or deploy cadence.
2. **Full rewrite** - rejected: too risky; would freeze feature development for
   months with no incremental value delivery.
3. **Keep flat structure** - rejected: complexity already causes coupling
   issues and makes AI-assisted development difficult. Hot files are growing.
4. **Hexagonal / ports-and-adapters per module** - partially adopted: each
   module has domain, application, and infrastructure layers, but we stop
   short of full hexagonal formality to avoid ceremony.

## Consequences

- Positive: clear ownership per domain; AI context is scoped to one module.
- Positive: dependency rules are enforceable by architecture tests in CI.
- Positive: Strangler migration lets old code run until new modules absorb it.
- Negative: more files and directories; navigation cost increases initially.
- Negative: contracts layer adds indirection; small changes touch more files.
- Neutral: `models.py` and `migrations.py` will eventually split per-module.
- Neutral: legacy `sync/rolling.py` is frozen; new indexing goes to
  `modules/indexing/`. Both coexist under feature flags until cutover.

## References

- docs/architecture.md
- docs/development/dependency-rules.md
- docs/development/migration-strategy.md