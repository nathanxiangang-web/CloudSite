# Architecture Debt Ratchet

CloudSite 2.0 is migrating from a legacy shared-core architecture to explicit
business modules and platform capabilities. The migration cannot be completed in
one change, so CI uses a **ratchet**: existing debt may remain temporarily, but
new debt is rejected.

## Current reviewed baseline

The M2 bootstrap records **90 exact debt IDs**:

| Rule | Baseline | Meaning |
| --- | ---: | --- |
| `module_legacy_import` | 25 | A business module still imports `cloudsite.models`, `cloudsite.database`, `cloudsite.services`, or `cloudsite.main`. |
| `router_orm_import` | 65 | A legacy router still imports SQLAlchemy, shared ORM models, or the legacy database layer directly. |
| `cross_module_internal_import` | 0 | A business module bypasses another module's `contracts/*` boundary. This is zero today and therefore locked at zero immediately. |

The 25 module legacy entries are concentrated in:

- automation: 12
- catalog: 4
- indexing: 4
- delivery: 3
- notifications: 1
- providers: 1

The 65 router entries split into 41 admin-router entries and 24 public-router
entries.

The reviewed machine-readable list lives in
`docs/development/architecture-debt-baseline.json`.

## Stable debt IDs

A debt ID is based on:

```text
<rule>::<file>::<dependency-surface>
```

Line numbers are intentionally excluded. Moving an import within the same file
does not create fake churn, while moving the dependency to another file is
correctly treated as a new architecture surface.

## CI behavior

`scripts/check-architecture-debt.py` parses Python imports with the standard
library AST.

On pull requests, CI reads the baseline from the **base branch**, not from the
pull request. This prevents a PR from hiding a new dependency by editing the
baseline in the same change.

Allowed:

- remove an existing debt ID;
- refactor code while keeping an already-baselined dependency surface;
- route a dependency through another module's `contracts/*`;
- move ORM work out of legacy routers into module/application/infrastructure code.

Rejected:

- introduce a new module dependency on the legacy shared core;
- introduce a new router-level ORM/database dependency;
- import another business module's domain/application/infrastructure/api
  internals;
- move an old dependency into a new file and claim the total count is unchanged.

## Baseline changes

Do **not** refresh the baseline as part of normal feature work.

The baseline may change only in a dedicated architecture-governance change that
explains why the policy itself must change. A feature PR that needs a new debt ID
must instead redesign the dependency through the supported module contract or
platform boundary.

As debt is removed, the committed baseline does not need to be edited
immediately: CI reports removed entries as good news and continues to reject new
ones. Periodic cleanup may shrink the baseline in a dedicated maintenance PR.

## Next convergence target

M3 should move application composition/wiring out of legacy `main.py` so
routers and module implementations can be assembled through one explicit
composition root. The ratchet introduced here will prevent that migration from
creating fresh legacy dependency surfaces elsewhere.
