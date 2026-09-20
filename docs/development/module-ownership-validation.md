# Module Ownership Validation

CloudSite uses each business module's `module.yaml` as the canonical registry
for ownership and allowed dependencies.

## CI gate

Run locally with:

```bash
python scripts/check-module-architecture.py
bash scripts/tests/test-module-architecture.sh
```

The validator enforces four properties.

### 1. One table, one owner

A physical business table may appear in the `owned_tables` list of only one
module.

Other modules may consume the owning module's contract, but may not claim
co-ownership simply because they read or project the table.

### 2. Declared dependencies form a DAG

Business dependencies declared as
`modules/<name>/contracts` must not form a cycle.

This keeps dependency direction reviewable and prevents two modules from
becoming mutually authoritative.

### 3. Contract imports must be declared

If production code imports another module through
`cloudsite.modules.<name>.contracts.*`, its manifest must include the matching
`modules/<name>/contracts` entry.

Internal cross-module imports remain forbidden by the existing architecture
gate.

### 4. Dependency targets must exist

Platform, module-contract, and plugin dependencies must resolve to known
repository boundaries.

## Ownership decisions established by this gate

The first enforcement pass resolves the ambiguous ownership that existed in the
initial module skeletons:

| Surface | Owner | Consumer / note |
| --- | --- | --- |
| `catalog_suggestions` | `automation` | Catalog consumes approved outcomes; suggestion workflow belongs to Automation. |
| `catalog_search_outbox` | `catalog` | Written with Catalog state so publication/index work can be emitted transactionally. |
| `catalog_search_projection_state` | `search` | Search owns rebuildable projection progress/state. |
| `download_events` | `delivery` | Delivery owns download tracking. |
| `download_diagnostics` | `delivery` | Delivery owns redirect/download diagnostics. |
| `folders`, `resources` | `resources` | Indexing may still mutate these through legacy adapters during migration, but target ownership remains Resources. |

The declared Catalog -> Search dependency is removed. Search may depend on the
Catalog public contract, but Catalog must not depend back on Search. Projection
work should move toward an event/outbox boundary instead of a synchronous
two-way module dependency.

## Migration note

This validator checks **declared target architecture**, while
`check-architecture-debt.py` tracks tolerated legacy implementation debt.

A module can therefore own a table in its manifest before every legacy import
has moved. The debt ratchet ensures those temporary compatibility paths can only
shrink.
