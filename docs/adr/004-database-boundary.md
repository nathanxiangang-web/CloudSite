# ADR-004: Database Boundary

Date: 2026-09-17
Status: Accepted
Supersedes: none

## Context

CloudSite uses two SQLite/Postgres databases: `state.db` (authoritative
instance state) and `index.db` (rebuildable content index). The legacy
codebase accesses these directly from services and routers with no boundary:

- Raw SQLAlchemy queries scattered across services and routers.
- No unit of work or transaction scope; commits happen mid-orchestration.
- Cross-module transaction assembly in routers (violates thin-router rule).
- No repository abstraction; ORM models are imported directly into services.
- Migrations are a single 78KB file; no per-module ownership.

## Decision

Establish a database boundary in `platform/db/`:

1. **Repository pattern**: each module owns a repository in
   `infrastructure/repository.py` that encapsulates its queries. Services call
   repositories, never the raw session.
2. **Unit of Work**: `platform/db/unit_of_work.py` defines transaction scope.
   A service opens a UoW, does work, commits or rolls back. No mid-flow commits.
3. **Two databases, clear roles**:
   - `state.db`: authoritative, migrated, never rebuilt. All business tables.
   - `index.db`: rebuildable FTS and projection state. Can be dropped and
     rebuilt from state.db with no data loss.
4. **Per-module migrations**: `migrations.py` splits into
   `platform/db/migrations/` with per-module migration files. Each module owns
   its schema.
5. **No cross-module transactions**: a service orchestrates within its own
   UoW; cross-module consistency is eventual via events, not a distributed
   transaction.

## Alternatives Considered

1. **Keep direct session access** - rejected: causes the coupling and
   mid-flow-commit problems we have today; untestable.
2. **Full ORM hiding (no SQLAlchemy leak)** - rejected: too much ceremony for
   the current team size. Repositories return domain objects but may use ORM
   internally.
3. **Single database** - rejected: keeping the rebuildable index separate lets
   us rebuild search without touching authoritative state, and lets the index
   use a different engine (e.g., FTS5) if needed.
4. **Distributed transactions (2PC)** - rejected: overkill for a monolith;
   eventual consistency via events is sufficient and simpler.

## Consequences

- Positive: testable services with mocked/in-memory repositories.
- Positive: clear transaction scope; no partial commits.
- Positive: per-module migrations enable independent schema evolution.
- Positive: index rebuild does not risk authoritative state.
- Negative: repository layer adds indirection and boilerplate per module.
- Negative: eventual consistency means search may lag state briefly.
- Neutral: the 78KB `migrations.py` splits over Phase 3-4; until then both
  the monolithic and per-module migration paths coexist.

## References

- platform/db/ (repository.py, unit_of_work.py, session.py, migrations/)
- docs/development/dependency-rules.md (Rule 2: thin router)
- ADR-001 (modular monolith)