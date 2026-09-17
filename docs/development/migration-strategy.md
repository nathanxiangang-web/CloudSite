# Migration Strategy

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

## Phase 1: Define boundaries (B1 — current)

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

- Move one module at a time from flat structure to `modules/<name>/`
- Order: identity → users → providers → shares → collections → catalog → search → resources → indexing → automation → delivery → notifications → submissions
- Each migration: move code, update imports, run tests, verify

## Phase 4: Legacy cleanup

- Delete `sync/rolling.py` after all providers migrated to new indexing
- Delete top-level `*.py` files after all modules migrated
- Consolidate `models.py` into per-module `infrastructure/models.py`
- Consolidate `migrations.py` into `platform/db/migrations/`

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

## What does NOT move

- `plugins/` — already well-structured, stays in place
- `plugins/ai/` — AI plugin stays as-is
- Test files — move with their modules in Phase 3
- Frontend (`apps/web/`) — not affected by backend module refactoring