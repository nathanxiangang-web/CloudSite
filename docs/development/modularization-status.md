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
| Indexing | `active` | Production v2 scan/reconcile is the active path. I2a moves operation logging to platform observability; I2b moves provider loading behind the Providers scan-source contract. |
| Search | `partial` | Public query/rebuild boundary exists. S2a moves dirty recovery into Search; S2b removes the caller-zero legacy row-level delta path. Remaining work: Catalog projection ownership and task-driven rebuild. |
| Resources | `partial` | Authoritative Folder/Resource persistence and public query/preview/download boundaries are module-owned. Remaining work is compatibility-facade/caller cleanup, not another persistence rewrite. |
| Providers | `partial` | Connection/root administration, download/preview runtime, and inventory scan-source composition are module-owned. Low-level AList transport compatibility still remains internal to Providers. |
| Identity | `partial` | Resource/folder identity persistence, matching, descendant path mutation boundary, and admin query boundary are module-owned. Remaining work is compatibility/migration orchestration cleanup only where callers still exist. |
| Catalog | `partial` | Core ORM/write side, public/admin query boundaries and publication scope are module-owned. Remaining work is legacy service/caller cleanup and Search projection convergence. |
| Automation | `partial` | Parser and suggestion cores are module-owned and tracked module legacy-import debt is zero. Compatibility facades may remain while callers migrate. |
| Delivery | `partial` | Download events, diagnostics and rate-limit ownership split are established. Continue only against verified legacy delivery-package callers. |
| Notifications | `partial` | ORM, user/admin query/command paths are module-owned. Remaining work is producer/event convergence where direct legacy producers still exist. |
| Shares | `partial` | CRUD/router persistence boundary is module-owned. Target/scope resolution and verification-attempt compatibility remain candidates for convergence. |
| Users | `partial` | Account/auth/session/user-data/role ownership is substantially module-owned. Admin-session ownership is the main documented follow-up. |
| Collections | `partial` | CRUD and reference resolution are module-owned. Topic/seed compatibility helpers remain follow-up only if still called. |
| Submissions | `partial` | User-to-review-to-publish workflow is module-owned; only narrow compatibility surfaces should remain. |
| Presentation | `partial` | Admin presentation lifecycle is module-owned; public Site/Home/setup callers may still use compatibility facades. |
| Setup | `partial` | First-run workflow is module-owned and composes owner contracts. Compatibility re-exports remain while installation behavior is preserved. |
| Site | `partial` | Site persistence is module-owned; top-level site settings remain a compatibility surface. |

## Active convergence order

The current backlog is tracked in issue #157. The intended order is:

1. keep documentation/current-state metadata reconciled;
2. narrow Indexing production-loader/logging compatibility;
3. prioritize Search S2 consistency/recovery work;
4. converge other `partial` modules only where a real production caller still crosses a legacy edge;
5. shift effort toward product/UI/E2E once the stop conditions are met.

## Stop conditions

Stop modularizing a domain when:

- production entry points use the module public contract;
- routers do not own ORM queries or cross-module internals;
- critical behavior has regression/E2E coverage;
- compatibility facades contain no new business logic;
- another refactor would not materially reduce risk or maintenance cost.

At that point, preserving a thin compatibility facade is preferable to architecture work for its own sake.
