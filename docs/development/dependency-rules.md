# Dependency Rules

## Rule 1: Modules import contracts only

Modules may not import another module's internal implementation.

**Forbidden:**
```python
from cloudsite.modules.catalog.infrastructure.models import CatalogEntry
from cloudsite.modules.shares.application.services import ShareService
```

**Allowed:**
```python
from cloudsite.modules.catalog.contracts.public import CatalogReader
from cloudsite.modules.shares.contracts.public import ShareScope
```

**Enforcement:** Architecture test scans `modules/*/` imports and rejects any import from `modules/<other>/{domain,application,infrastructure,api}/`.

---

## Rule 2: Router is thin

API routers only:
1. Parse requests
2. Check permissions
3. Call application service
4. Return response

**Forbidden in routers:**
- Multi-step SQL
- Cross-module transaction assembly
- State machine logic
- Retry logic
- Provider call strategy
- Indexing strategy

**Enforcement:** Code review + architecture test checks that `api/router.py` files do not import `sqlalchemy` directly or call `session.commit()`.

---

## Rule 3: No `cloudsite.main` dependency

No module may import from `cloudsite.main`.

**Forbidden:**
```python
from cloudsite.main import app
from cloudsite import main
```

`main.py` (or `app/api.py`) only:
- Creates FastAPI
- Registers routers
- Registers middleware
- Manages lifecycle
- Dependency injection

**Enforcement:** Architecture test scans all `modules/` and `platform/` files for `from cloudsite.main` or `from cloudsite import main` imports.

---

## Rule 4: Platform cannot depend on modules

Dependency direction is `modules → platform` only.

**Allowed:**
```text
modules → platform
modules → modules (via contracts only)
```

**Forbidden:**
```text
platform → modules
platform → catalog
platform → shares
platform → automation
```

**Enforcement:** Architecture test scans `platform/` imports and rejects any import from `cloudsite.modules.*`.

---

## Rule 5: Legacy freeze

`sync/rolling.py` and `indexer.py` are legacy. No new 2.0 logic may be added.

**Enforcement:** Code review gate on PRs touching `sync/rolling.py` or `indexer.py`.

---

## Rule 6: New code goes to new structure

All new 2.0 code must go to `modules/`, `platform/`, or `app/`. No new top-level files in `cloudsite/`.

**Enforcement:** CI check rejects new `.py` files directly under `apps/api/cloudsite/` (excluding `__init__.py`, `main.py`, `config.py`).