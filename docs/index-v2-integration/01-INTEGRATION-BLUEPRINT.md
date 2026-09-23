# CloudSite 1.0.0 × Index-V2 Integration Blueprint

> Architecture owner: Architect
>
> Control issue: #223
>
> Communication protocol: `00-COMMUNICATION-PROTOCOL.md`
>
> This blueprint is intentionally a **final integration blueprint**, not a CloudSite 2.0 continuation plan.

## 1. Mission

Build one final CloudSite release by keeping the complete **CloudSite 1.0.0 product** and replacing only its indexing execution path with the proven parts of the **index-v2** indexing engine.

After the release passes acceptance and recovery tests, CloudSite enters maintenance/frozen state. No AI, database rewrite, UI redesign, or wider 2.0 modularization is part of this project.

## 2. Frozen baselines

### Product baseline

```text
main / v1.0.0
c46a1d94c10d29ba0168f6c5988bc5ce75cdc69c
```

At architecture freeze, `main` and `v1.0.0` are identical.

### Index source snapshot

```text
index-v2
d0b62b0a6970d9bf65070118a890a18adebe5ef1
```

The source snapshot is used for analysis and selective porting. It is **not** an integration base.

### Integration base

```text
main/v1.0.0
  └── arch/index-v2-integration
       └── future integration/index-v2-final
            └── worker branches
```

No whole-branch merge from `index-v2` is permitted.

## 3. Why selective integration is mandatory

Compared with `v1.0.0`, `index-v2` contains hundreds of commits and broad changes across indexing, catalog, identity, delivery, automation, database migration, modularization, and application composition.

Therefore this is not a branch merge project. It is a **capability extraction and compatibility integration project**.

The rule is:

```text
take indexing behavior, not CloudSite 2.0 ownership structure
```

## 4. Product scope

### Must remain CloudSite 1.0.0 behavior

The final release preserves the existing 1.0.0 product contract unless a task explicitly documents a compatibility fix:

- public browsing;
- search;
- resource detail;
- image/video/PDF/text/Office preview behavior;
- HTTP 302 download behavior through AList;
- favorites and history;
- playback progress;
- collections;
- personal shares and limits;
- public/admin authentication;
- existing AList connection management;
- Docker Compose deployment model;
- SQLite backup/recovery behavior;
- existing frontend UI and routes.

### New/changed capability

Only indexing execution and the minimum supporting internal state required for index-v2 are changed.

### Explicit non-goals

Do not integrate:
- V2 Catalog redesign;
- V2 Automation;
- V2 Delivery redesign;
- V2 user/auth modularization;
- V2 frontend feature restructuring;
- AI/plugin work;
- general database rewrite;
- PostgreSQL migration;
- R9 production audit/repair pipeline;
- R10 native-provider delta production wiring;
- unrelated cleanup merely because V2 has a “better” implementation.

## 5. Index-v2 capability selection

The index-v2 development record is treated as source evidence, not as an instruction to port everything.

### Required source capability

| V2 stage | Capability | Final integration decision |
|---|---|---|
| R0 | safety baseline / destructive-write guards | PORT |
| R1 | bounded concurrent directory scan | PORT |
| R2 | durable scan runs, directory checkpoints, resume | PORT |
| R3 | complete gate, atomic reconcile, shrink safety | PORT |
| R4 | stable identity behavior | PORT through 1.0 compatibility adapter |
| R5 | root lifecycle / generation safety | PORT minimum required semantics |
| R6 | dirty-scope/incremental foundations | PORT only if it reduces re-scan safely |
| R7 | search delta / dirty-state semantics | PORT through 1.0 search adapter |
| R8 | rolling verification | FEATURE-GATED; requires real AList E2E |
| R9 | full audit/repair | EXCLUDE |
| R10 | native provider delta | EXCLUDE from production path |

### R8 rule

R8 may be enabled only after a real AList test proves:
- unchanged directories remain stable;
- mismatch produces a safe dirty scope;
- provider failure is isolated;
- verification progresses over repeated scheduler runs;
- no destructive removal can occur from an incomplete verification pass.

If this gate is not satisfied, the final product uses safe scheduled durable scans rather than an unverified R8 path.

## 6. Target architecture

The final architecture is a strangler replacement inside the 1.0.0 product.

```text
Browser / Admin UI
        |
        v
1.0.0 FastAPI routes
        |
        v
1.0.0 sync/index compatibility facade
        |
        +-----------------------------+
        |                             |
        | feature flag OFF            | feature flag ON
        v                             v
legacy 1.0 indexer              index_v2 runtime
                                      |
                 +--------------------+---------------------+
                 |                    |                     |
                 v                    v                     v
          v1 AList adapter     v1 persistence adapter   v1 identity adapter
                 |                    |                     |
                 v                    v                     v
            AList cache/API       Folder/Resource      existing 1.0 identity
                                      |
                                      v
                              v1 search projection
                                      |
                                      v
                                 search/index.db
```

### Core rule

Index-v2 must depend on **ports owned by the integration package**, not on V2 business modules.

Prohibited dependency direction:

```text
index_v2 -> modules/catalog
index_v2 -> modules/resources implementation
index_v2 -> modules/identity implementation
index_v2 -> modules/delivery
index_v2 -> CloudSite 2.0 composition
```

Permitted direction:

```text
index_v2 core -> local ports
1.0 adapters -> implement local ports using 1.0 code
```

## 7. Proposed target package

Do not introduce the entire V2 `modules/` and `platform/` hierarchy into the 1.0.0 branch.

Use a narrow package:

```text
apps/api/cloudsite/index_v2/
├── __init__.py
├── contracts.py
├── domain/
│   ├── snapshot.py
│   ├── identity.py
│   ├── directory_fingerprint.py
│   ├── index_change.py
│   └── verification_result.py        # only if R8 enabled
├── application/
│   ├── scan.py
│   ├── reconcile.py
│   ├── dirty_scope.py
│   └── search_projection.py
├── runtime/
│   ├── coordinator.py
│   ├── checkpoint.py
│   └── status.py
└── adapters/
    ├── alist_v1.py
    ├── persistence_v1.py
    ├── identity_v1.py
    ├── search_v1.py
    └── status_v1.py
```

Names may be adjusted after Phase 0 dependency analysis, but the ownership principle may not.

## 8. Integration ports

The architect expects the following minimal interfaces.

### ProviderScanPort

Responsibilities:
- list one directory through the existing AList connection;
- return provider-neutral entries;
- expose root identity and capabilities;
- never expose V2 Provider ORM.

### ResourceStorePort

Responsibilities:
- read current Folder/Resource state for one root/scope;
- atomically apply safe reconcile output;
- preserve 1.0.0 resource schema and external IDs;
- refuse destructive commit from incomplete scan state.

### IdentityPort

Responsibilities:
- reuse existing 1.0 identity resolution where possible;
- preserve IDs across safe rename/move cases;
- scope identity by root mapping;
- surface ambiguity rather than silently merging.

### SearchProjectionPort

Responsibilities:
- mark/rebuild/update the existing 1.0 search index;
- preserve current search API behavior;
- recover safely if projection fails after inventory commit.

### ProgressStorePort

Responsibilities:
- persist scan/run/directory/checkpoint state;
- support restart/resume;
- expose progress to existing admin status surfaces through a compatibility facade.

## 9. Database ownership

### state.db

Remain authoritative for 1.0.0 instance state.

No new V2 business tables are allowed in `state.db` without an ADR.

Content-root mappings and AList credentials remain owned by the existing 1.0.0 model.

### index.db

Remain rebuildable.

New V2 staging/progress tables may be added here when needed, expected minimum:

```text
index_scan_runs
index_scan_dirs
index_scan_entries
```

Additional tables such as root state, dirty scope, or verification state require a task-specific justification and migration test.

### Existing Folder/Resource tables

They remain the authoritative 1.0.0 index representation consumed by browse/search/detail/download flows.

The final integration does **not** require migrating the product to the V2 Resources module.

## 10. Scan transaction model

The safe path is:

```text
START RUN
  ↓
enumerate root
  ↓
claim directory
  ↓
read directory from AList
  ↓
checkpoint entries + discovered child directories
  ↓
mark directory done
  ↓
repeat / resume after crash
  ↓
COMPLETE GATE
  ↓ only when every required directory is complete
build reconcile plan
  ↓
safety guards
  ↓
atomic apply to Folder/Resource
  ↓
identity history/update
  ↓
search projection
  ↓
mark run completed
```

Critical invariant:

> An incomplete scan may stage data and progress, but may not produce destructive removals in the live 1.0.0 index.

## 11. Restart/resume semantics

A durable run must survive process restart.

Required behavior:
- completed directories are not scanned again during same-run resume;
- stale `running` directories become retryable/pending;
- run/root fingerprint compatibility is checked before resume;
- resume is rejected when the root mapping meaningfully changed;
- repeated checkpoint write is idempotent;
- completed reconcile is idempotent;
- a failed scan cannot be reported as successful by admin status.

No worker may “simplify” resume to restart-from-zero without architect approval.

## 12. Identity compatibility

The final product must not silently create new public resource IDs merely because indexing internals changed.

The integration must test:
- unchanged path/object -> same ID;
- safe rename within same root -> expected stable identity behavior;
- move within same root -> expected stable identity behavior;
- ambiguous fingerprint -> conflict/no unsafe merge;
- cross-root move -> no unsupported identity merge;
- deleted then reappearing object -> defined behavior matching the compatibility contract.

The exact 1.0 identity adapter behavior is frozen in Phase 0 before implementation.

## 13. Search consistency

Inventory correctness has priority over search projection.

Preferred transaction boundary:

```text
inventory commit succeeds
    ↓
search projection attempts
    ├─ success -> clean
    └─ failure -> mark search dirty -> recover/rebuild
```

Search failure must not roll back a correct durable scan into an unknown state.

The user-visible search API remains 1.0.0-compatible.

## 14. Scheduler and admin compatibility

Existing 1.0.0 scheduler/admin routes remain the public control plane.

They call a compatibility facade that selects:

```text
legacy engine       when feature flag OFF
index-v2 engine     when feature flag ON
```

No frontend migration is required merely to expose the new engine.

The compatibility facade must preserve:
- manual sync trigger semantics;
- “sync already running” protection;
- startup/recovery behavior;
- progress/status visibility;
- cooldown/circuit safety where still applicable.

## 15. Rollout flags

Initial implementation must be reversible.

Minimum flag:

```text
CLOUDSITE_INDEX_V2_ENABLED=false
```

Optional separate flags require architect approval.

Until the cutover gate:
- default remains false;
- legacy execution code remains intact;
- index-v2 can run in test/shadow mode.

## 16. Shadow verification gate

Before production cutover, run index-v2 against the same AList/root configuration without allowing it to destructively mutate the live 1.0.0 inventory.

Shadow evidence must compare at least:
- folder count;
- resource count;
- paths;
- sizes/mtime metadata where meaningful;
- stable identity mapping;
- additions/removals/updates;
- suspicious shrink/churn.

Any unexplained destructive diff blocks cutover.

## 17. Cutover strategy

### Step A — legacy baseline
Record a known-good 1.0.0 index snapshot and relevant counts.

### Step B — V2 shadow
Run durable index-v2 staging and reconcile planning with writes disabled or redirected.

### Step C — compare
Resolve all material differences.

### Step D — V2 live canary
Enable V2 for one controlled root/environment.

### Step E — restart/resume
Interrupt an unfinished scan, restart process, resume same run, finish cleanly.

### Step F — full cutover
Enable V2 as active indexing engine.

### Step G — fallback window
Keep legacy engine code available until final release acceptance is complete.

Only then may dead legacy execution paths be frozen or minimally removed. Historical data/views may remain.

## 18. Software development lifecycle

### Phase 0 — Requirements and contract freeze

Outputs:
- this blueprint;
- communication protocol;
- capability matrix;
- 1.0 compatibility contract;
- path ownership map;
- regression baseline.

No production implementation.

Gate P0:
Architect marks Phase 0 accepted.

### Phase 1 — Core extraction

Goal:
Create a dependency-light index-v2 core with pure/domain logic and unit tests.

May include:
- snapshot;
- directory scanning orchestration contracts;
- reconcile planning;
- durable checkpoint logic;
- safety guards;
- identity matching pure logic.

Must not alter production routing.

Gate P1:
Core tests pass with fake ports and no V2 business-module imports.

### Phase 2 — 1.0 adapters

Goal:
Implement adapters for AList, Folder/Resource persistence, identity, status, and search.

Gate P2:
Adapter integration tests pass against 1.0 schemas.

### Phase 3 — orchestration and compatibility facade

Goal:
Wire manual/admin/scheduler entry points behind the feature flag.

Gate P3:
Legacy mode remains unchanged and V2 mode can execute in controlled test mode.

### Phase 4 — shadow and destructive-safety validation

Goal:
Compare V2 result with known-good 1.0 state.

Gate P4:
No unexplained destructive diff; incomplete scans cannot delete live records.

### Phase 5 — real AList E2E

Required scenarios:
1. clean initial scan;
2. add file/folder;
3. modify metadata;
4. delete;
5. rename/move within root;
6. multiple roots;
7. provider failure;
8. interrupted scan;
9. process restart/resume;
10. repeated run idempotency;
11. suspicious mass shrink;
12. search projection recovery.

Gate P5:
All release-blocking scenarios pass.

### Phase 6 — cutover and regression

Run the complete affected 1.0.0 regression suite:
- browse;
- search;
- detail;
- preview;
- download;
- admin;
- auth boundary;
- backup/recovery relevant to index.db.

Gate P6:
No blocking regression.

### Phase 7 — release and project freeze

Outputs:
- release tag;
- release notes;
- deployment/rollback notes;
- final known limitations;
- archived/frozen project status.

After this gate, no roadmap expansion is implied.

## 19. Four-worker execution lanes

Parallelism is allowed only under the communication protocol.

### W1 — Index core
Primary ownership:
`apps/api/cloudsite/index_v2/domain/**`
`apps/api/cloudsite/index_v2/application/**`

Responsibilities:
- extract pure/core V2 behavior;
- unit tests;
- no knowledge of 1.0 ORM internals.

### W2 — Persistence and identity adapters
Primary ownership:
`apps/api/cloudsite/index_v2/adapters/persistence_v1.py`
`apps/api/cloudsite/index_v2/adapters/identity_v1.py`
migration files explicitly assigned by architect.

Responsibilities:
- 1.0 Folder/Resource mapping;
- identity stability;
- staging/progress persistence;
- atomic/destructive safety.

### W3 — Provider/runtime/control-plane adapters
Primary ownership:
`alist_v1.py`
`runtime/**`
compatibility facade and explicitly assigned scheduler/admin integration.

Responsibilities:
- AList listing;
- bounded concurrency;
- progress/status;
- manual/scheduler/startup wiring;
- feature flag.

### W4 — Verification and release QA
Primary ownership:
tests, E2E scripts, fixtures, compatibility snapshots, release verification docs.

Responsibilities:
- baseline regression;
- shadow comparison;
- restart/resume E2E;
- multi-root E2E;
- failure injection;
- release evidence.

W4 does not “fix production code while testing” without a separate task.

## 20. Initial work breakdown

These are blueprint work packages, not yet authorized implementation Issues.

### P0 discovery

- `IDX-P0-001`: freeze V2 capability/file dependency matrix.
- `IDX-P0-002`: freeze 1.0 persistence + identity compatibility contract.
- `IDX-P0-003`: freeze 1.0 scheduler/admin/search entrypoint contract.
- `IDX-P0-004`: create regression baseline and real-AList E2E fixture plan.

### P1 core

- `IDX-P1-001`: extract snapshot/domain primitives.
- `IDX-P1-002`: extract durable scan/checkpoint core.
- `IDX-P1-003`: extract reconcile + destructive safety.
- `IDX-P1-004`: core unit/contract tests.

### P2 adapters

- `IDX-P2-001`: AList v1 scan adapter.
- `IDX-P2-002`: Folder/Resource persistence adapter.
- `IDX-P2-003`: identity adapter.
- `IDX-P2-004`: search/status adapters.

### P3 integration

- `IDX-P3-001`: feature flag + compatibility facade.
- `IDX-P3-002`: manual admin sync wiring.
- `IDX-P3-003`: scheduler/startup wiring.
- `IDX-P3-004`: rollback/fallback path.

### P4-P6 verification

- shadow compare;
- interruption/resume;
- multi-root;
- destructive guard;
- search recovery;
- full 1.0 regression;
- release packaging.

Each package becomes a separate Issue only after the preceding gate and architect review.

## 21. Hard release acceptance criteria

The project cannot be declared complete until all are true:

- [ ] Final branch is based on 1.0.0, not V2 mainline.
- [ ] No unrelated V2 modules were imported.
- [ ] Empty index -> complete initial V2 index works.
- [ ] Subsequent additions are detected correctly.
- [ ] Deletions are applied only after a complete/safe scan.
- [ ] Rename/move identity behavior matches frozen contract.
- [ ] Multiple roots cannot overwrite or delete each other.
- [ ] Interrupted scan safely resumes after restart.
- [ ] Re-running completed work is idempotent.
- [ ] Mass shrink/churn safety blocks unsafe destructive writes.
- [ ] Search reflects committed inventory and can recover when dirty.
- [ ] Existing browse/detail/preview/download paths remain functional.
- [ ] Existing admin/manual sync controls remain usable.
- [ ] Backup/rebuild story for new index.db tables is documented.
- [ ] Rollback to legacy engine is tested before final cutover.
- [ ] Real AList E2E evidence exists.
- [ ] Release artifacts build successfully.
- [ ] Final documentation identifies known limitations.
- [ ] Project freeze status is recorded.

## 22. Stop condition

The project ends when:

```text
CloudSite 1.0.0 product
+ safely integrated index-v2 engine
+ tested deployment/recovery
+ final release
= DONE
```

The following are not reasons to continue:
- code could be cleaner;
- V2 has additional modules;
- AI could be added;
- UI could be redesigned;
- database architecture could be modernized;
- another refactor appears attractive.

Any future development after project freeze is a new project decision, not unfinished work from this blueprint.
