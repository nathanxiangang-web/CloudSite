# Migration Strategy

## Current status

The phase descriptions below are the original Strangler-migration roadmap, not a live phase tracker. CloudSite is now in modularization convergence/cleanup: the architecture-debt baseline is `module_legacy_import=0` and `router_orm_import=0`, and Indexing is already `active` in its manifest. Use [modularization-status.md](./modularization-status.md) and issue #157 for the active order of work.

## Approach: Strangler Migration

Old code continues to run. New modules absorb new paths. Legacy is frozen. Eventually legacy is deleted.

```text
Legacy Rolling
     ↓
New Inventory (modules/indexing/)
     ↓
部分 Provider 迁移
     ↓
全部 Provider 迁移
     ↓
Legacy Freeze (no new code)
     ↓
Legacy Delete
```

## Phase 1: Define boundaries (historical B1)

- Create `modules/`, `platform/`, `app/` directory structure
- Write architecture docs and dependency rules
- Add architecture tests
- No code movement yet

## Phase 2: New code in new structure (B2-B4)

- New Task/Worker system → `platform/tasks/`
- New Indexing module → `modules/indexing/`
- New Repository pattern → `modules/<name>/infrastructure/repository.py`
- All new code goes to new directories

## Phase 3: Gradual migration (post-batch-1)

### Backend

- Move one module at a time from flat structure to `modules/<name>/`
- Order: identity → users → providers → shares → collections → catalog → search → resources → indexing → automation → delivery → notifications → submissions
- Each migration: move code, update imports, run tests, verify

### Frontend

Frontend is part of the 2.0 modularization effort and must migrate by feature boundary instead of continuing to grow route-local pages and the global stylesheet.

Target shape:

```text
apps/web/src/
├── app/                    # route shells only
├── features/               # business feature modules
│   ├── catalog/
│   ├── search/
│   ├── indexing/
│   ├── automation/
│   ├── shares/
│   ├── users/
│   └── resources/
├── components/
│   └── ui/                 # shared presentational primitives
├── lib/
│   └── api/                # shared transport / API primitives
└── styles/
    ├── tokens.css
    ├── base.css
    └── layout.css
```

Rules:

- `app/**/page.tsx` is a route entry and composition shell, not the home of feature logic.
- Feature-specific components, hooks, API calls, state, and styles belong in `features/<name>/`.
- New feature-specific CSS must not be appended to `app/globals.css`.
- `globals.css` is treated as legacy and will shrink over time into tokens, resets, and global layout rules.
- Shared UI primitives go to `components/ui/`; business components do not.
- Cross-feature imports must go through each feature's public entry point, not internal files.
- Frontend migration follows the same Strangler approach: new code uses the new structure, existing pages move feature-by-feature.

## Phase 4: Legacy cleanup

### Backend

- Delete legacy sync/indexing paths after the new indexing path fully replaces them
- Delete top-level `*.py` files after all modules migrated
- Consolidate `models.py` into per-module `infrastructure/models.py`
- Consolidate `migrations.py` into `platform/db/migrations/`

### Frontend

- Reduce `app/globals.css` to design tokens, resets, shared layout, and truly global styles
- Move business-page CSS into feature-local styles
- Split large route pages into feature views/components/hooks
- Move route-local API logic into `features/<name>/api.ts` or shared `lib/api/`
- Keep `app/` focused on routing, layouts, loading/error boundaries, and feature composition

## Current-to-target mapping

| Current | Target | Phase |
|---------|--------|-------|
| `main.py` | `app/api.py` + `app/composition.py` | 3 |
| `infrastructure/lifespan.py` | `app/lifecycle.py` | 3 |
| `config.py` | `platform/settings/` | 3 |
| `database.py` | `platform/db/` | 3 |
| `models.py` | `modules/*/infrastructure/models.py` | 4 |
| `migrations.py` | `platform/db/migrations/` | 4 |
| `auth.py`, `users.py`, `userdata.py` | `modules/users/api/` | 3 |
| `sessions.py` | `modules/users/` | 3 |
| `admin_auth.py` | `modules/users/api/` | 3 |
| `alist.py` | `modules/providers/infrastructure/` | 3 |
| `indexer.py` | `modules/indexing/` (rewrite) | 4 |
| `search.py` | `modules/search/` | 3 |
| `preview.py`, `download.py` | `modules/resources/api/` | 3 |
| `sync/rolling.py` | frozen → delete | 4 |
| `tasks/` | `platform/tasks/` | 2 |
| `services/catalog*.py` | `modules/catalog/` | 3 |
| `services/suggestion_*.py` | `modules/automation/` | 3 |
| `routers/` | `modules/*/api/` | 3 |
| `routers/admin/` | `modules/*/api/` | 3 |
| `infrastructure/` | `platform/http/`, `platform/security/` | 3 |
| `plugins/` | stays as `plugins/` | — |
| `shares/` | `modules/shares/` | 3 |
| `identity/` | `modules/identity/` | 3 |
| `providers/` | `modules/providers/` | 3 |
| `apps/web/src/app/**/page.tsx` feature logic | `apps/web/src/features/<feature>/` | 3 |
| `apps/web/src/app/globals.css` business styles | feature-local styles + `styles/` | 3-4 |
| route-local API/state logic | `features/<feature>/api.ts`, hooks, state | 3 |
| shared visual primitives | `components/ui/` | 3 |

## What does NOT move

- `plugins/` — already well-structured, stays in place
- `plugins/ai/` — AI plugin stays as-is
- Backend test files move with their modules in Phase 3
- Frontend route ownership remains under Next.js `app/`, but business implementation moves behind feature boundaries under `features/`