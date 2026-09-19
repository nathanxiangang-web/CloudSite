# Architecture Debt Ratchet

CloudSite 2.0 is migrating from a legacy shared-core architecture to explicit
business modules and platform capabilities. The migration cannot be completed in
one change, so CI uses a **monotonic ratchet**: architecture debt may remain
temporarily, but it may only decrease.

## Current baseline

The current reviewed baseline records **41 exact debt IDs**:

| Rule | Baseline | Meaning |
| --- | ---: | --- |
| `module_legacy_import` | 0 | A business module still imports `cloudsite.models`, `cloudsite.database`, `cloudsite.services`, or `cloudsite.main`. |
| `router_orm_import` | 41 | A legacy router still imports SQLAlchemy, shared ORM models, or the legacy database layer directly. |
| `cross_module_internal_import` | 0 | A business module bypasses another module's `contracts/*` boundary. This stays locked at zero. |

The baseline tightened from 90 to 88 after the Identity admin diagnostics
router stopped importing SQLAlchemy and `cloudsite.models`, then to 87 when
Indexing stopped importing shared Folder/Resource ORM through `cloudsite.models`,
to 86 when the Resources router stopped constructing SQLAlchemy queries, and
to 85 when preview lookups stopped importing shared Resource ORM in that router,
and to 84 when Providers stopped importing `AListConnection` from `cloudsite.models`,
and to 83 when the preview router stopped importing shared Resource ORM,
and to 82 when the download router stopped importing shared Resource ORM,
and to 81 when Delivery download-event persistence stopped importing shared ORM,
and to 79 when rate-limit persistence moved from Delivery legacy imports to Resources,
and to 76 when Indexing removed its remaining shared ORM/session imports,
and to 71 when Notifications took ORM/query ownership and its user/admin routers became ORM-free,
and to 67 when Catalog core application stopped importing shared models/services and moved its state ORM behind module ownership,
and to 59 when Automation's parser subdomain took ownership of parser task ORM, deterministic parsing, and Resource parser reads,
and to 58 when frozen legacy sync reads moved behind the Indexing contract and Automation seeding stopped importing shared sync/resource ORM,
and to 55 when Automation took ownership of suggestion state and routed all Resource/Catalog interaction through public contracts,
and to 52 when three thin router debts were removed: two unused ORM/SQLAlchemy imports and admin auth's provider lookup moved behind the Providers public contract,
and to 51 when public Delivery feedback audit writes moved to the persistence-neutral observability writer,
and to 50 when public Catalog entry totals moved behind the Catalog application count query and the router dropped SQLAlchemy,
and to 49 when public Catalog entry/release/asset projections moved into Catalog ownership and the download path switched to Resources + Providers contracts,
and to 45 when Collections took ownership of its ORM and both public/admin routes moved behind Collections, Resources, Catalog, and Providers contracts,
and to 41 when User/Submission ORM ownership and the complete Submission lifecycle moved behind Users, Submissions, Resources, Providers, Notifications, and Observability contracts.

The machine-readable list lives in
`docs/development/architecture-debt-baseline.json`.

## Stable debt IDs

A debt ID is based on:

```text
<rule>::<file>::<dependency-surface>
```

Line numbers are intentionally excluded. Moving an import within the same file
does not create fake churn, while moving the dependency to another file is
correctly treated as a new architecture surface.

## Two enforcement locks

`scripts/check-architecture-debt.py` parses Python imports with the standard
library AST and applies two independent checks.

### Lock 1: no debt may be introduced

For pull requests, CI reads the previous baseline from the PR base branch.

For pushes directly to `main`, CI reads the previous baseline from
`github.event.before`.

The current code may not contain any debt ID that was absent from that previous
baseline. Updating the baseline in the same change cannot self-approve new debt.

### Lock 2: the committed baseline must equal current code

The baseline committed in the current revision must exactly match the scanner's
current result.

This means that when a migration removes debt, the same change must remove those
IDs from the baseline. A deleted dependency cannot remain as an unused
allow-list entry and later reappear.

Example:

```text
90 -> 88 -> 87 -> 86 -> 85 -> 84 -> 83 -> 82 -> 81 -> 79 -> 76 -> 71 -> 67 -> 59 -> 58 -> 55 -> 52 -> 51 -> 50 -> 49 -> 45 -> 41 -> ... -> 0
```

The ratchet therefore records the actual current debt, not the historical
maximum debt.

## Allowed changes

- remove an existing debt ID and ratchet the baseline in the same change;
- refactor code while keeping an already-baselined dependency surface;
- route a dependency through another module's `contracts/*`;
- move ORM work out of legacy routers into module application/infrastructure
  code.

## Rejected changes

- introduce a new module dependency on the legacy shared core;
- introduce a new router-level ORM/database dependency;
- import another business module's domain/application/infrastructure/api
  internals;
- move an old dependency into a new file and claim the total count is unchanged;
- remove debt from code but leave the removed ID in the current baseline;
- add new debt and attempt to whitelist it by editing the baseline in the same
  change.

## Updating the baseline after legitimate debt removal

After removing architecture debt, generate the scanner result with:

```bash
python scripts/check-architecture-debt.py --print-baseline
```

Review the generated payload and replace
`docs/development/architecture-debt-baseline.json` with that exact result.

The baseline is not a manually maintained exception list. It is a checked-in
snapshot of the debt that still exists.

## Self-test

`scripts/tests/test-architecture-debt-ratchet.sh` deliberately verifies both
failure modes:

1. fresh module/router/cross-module dependency debt is rejected;
2. stale debt left in the baseline after code removal is rejected.

The final self-test then verifies that the clean tree and its committed baseline
match exactly.
