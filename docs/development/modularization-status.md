# Modularization Status

This file is the human-readable **current-state index** for CloudSite modularization.
It exists to prevent historical migration plans from being mistaken for the active backlog.

Last reconciled: 2026-09-20.

## Source-of-truth order

When documents disagree, use this order:

1. runtime code and tests on `main`;
2. each module's `module.yaml` for machine-enforced ownership/dependencies/status;
3. each module's `README.md` for the current compatibility edges;
4. this file for cross-module convergence priorities;
5. `*-module-migration.md`, `catalog-frontend-migration.md`, and the phase sections in
   `migration-strategy.md` as **historical execution records**.

A historical section labelled `Next`, `Then`, or `Later slices` is not automatically
an active task. Re-check the current module README, code, tests, and issue #157 first.

## Current architecture baseline

The architecture-debt ratchet is currently:

- `module_legacy_import = 0`
- `router_orm_import = 0`

This means modularization work is now in **convergence/cleanup**, not broad migration.
A module being `partial` does not by itself justify more refactoring.

## Module status

| Module | Manifest | Current convergence note |
| --- | --- | --- |
| Indexing | `active` | Production v2 scan/reconcile is the active path. I2a operation logging now uses platform observability; I2b consumes Providers-owned scan sources. Remaining legacy helpers are compatibility-only and should be removed only after caller-zero verification. |
| Search | `partial` | S2a-d structural convergence is complete: dirty recovery, dead row-delta removal, Catalog projection ownership, and a pure `cloudsite.search` facade. Synchronous rebuild is intentionally retained until worker deployment becomes invariant or scale/UX provides evidence for task-driven behavior. |
| Resources | `partial` | Authoritative Folder/Resource persistence and public query/preview/download boundaries are module-owned. Remaining work is compatibility-facade/caller cleanup, not another persistence rewrite. |
| Providers | `partial` | Connection/root administration, download/preview runtime, and inventory scan-source composition are module-owned. Low-level AList transport compatibility still remains internal to Providers. |
| Identity | `partial` | Resource/folder identity persistence, matching, descendant path mutation boundary, and admin query boundary are module-owned. Remaining work is compatibility/migration orchestration cleanup only where callers still exist. |
| Catalog | `partial` | Core ORM/write/public/admin/publication boundaries are module-owned. Catalog also owns the search outbox/source DTO side; Search owns projection persistence. Remaining work is verified legacy service/caller cleanup only. |
| Automation | `partial` | Parser and suggestion cores are module-owned and tracked module legacy-import debt is zero. Compatibility facades may remain while callers migrate. |
| Delivery | `partial` | Download events/diagnostics/rate-limit ownership is established and production download/share-download routes consume module public contracts directly (D4a). The separate delivery-package legacy service remains intentionally deferred because migrating it would require another ORM + Catalog boundary rewrite. |
| Notifications | `partial` | ORM, user/admin query/command paths are module-owned. Remaining work is producer/event convergence where direct legacy producers still exist. |
| Shares | `partial` | CRUD, verification-attempt persistence/cleanup, and production target/scope orchestration are module-owned behind Resources/Collections contracts. Remaining legacy share services are compatibility surfaces subject to caller audit, not automatic migration. |
| Users | `partial` | Account/auth/session/user-data/role ownership is substantially module-owned. Admin-session ownership is the main documented follow-up. |
| Collections | `partial` | CRUD and reference resolution are module-owned. Topic/seed compatibility helpers remain follow-up only if still called. |
| Submissions | `partial` | User-to-review-to-publish workflow is module-owned; only narrow compatibility surfaces should remain. |
| Presentation | `partial` | Admin presentation lifecycle is module-owned; public Site/Home/setup callers may still use compatibility facades. |
| Setup | `partial` | First-run workflow is module-owned and composes owner contracts. Compatibility re-exports remain while installation behavior is preserved. |
| Site | `partial` | Site persistence is module-owned; top-level site settings remain a compatibility surface. |

## Active convergence order

The current backlog is tracked in issue #157. Indexing I2 and Search S2 have reached their current stop points, so they are no longer the default next refactor targets.

The intended order is now:

1. keep documentation/current-state metadata reconciled;
2. treat Shares P2a/P2b production ownership as converged; only reduce remaining legacy wrappers after caller-zero verification;
3. inspect Users admin-session ownership and other `partial` modules only where a real production caller still crosses a legacy edge;
4. preserve thin caller-zero compatibility facades when deleting them would not materially reduce risk;
5. shift effort toward product/UI/E2E once the stop conditions are met.

Do not reopen completed Indexing/Search work merely because their manifests or historical migration documents still contain `partial` language.

## Stop conditions

Stop modularizing a domain when:

- production entry points use the module public contract;
- routers do not own ORM queries or cross-module internals;
- critical behavior has regression/E2E coverage;
- compatibility facades contain no new business logic;
- another refactor would not materially reduce risk or maintenance cost.

At that point, preserving a thin compatibility facade is preferable to architecture work for its own sake.
