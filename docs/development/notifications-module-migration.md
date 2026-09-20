# Notifications Module Migration

> **Historical execution record.** This document preserves the slice-by-slice migration plan and invariants at the time it was written. It is not the current backlog. Before acting on any `Next`, `Then`, or `Later` item here, check `module.yaml`, the module `README.md`, [modularization-status.md](./modularization-status.md), and issue #157 against current `main`.


Notifications owns in-app notification persistence and user/admin notification
query/command behavior. Business producers should eventually publish events or
call the Notifications public contract instead of writing shared ORM directly.

## N1 — ORM and router boundary

Status: implemented.

`Notification` now lives in
`modules/notifications/infrastructure/models.py`. The legacy
`cloudsite.models.Notification` symbol re-exports the exact same SQLAlchemy
class, so existing producers and migrations remain compatible without a schema
migration.

The application layer owns:

- user-visible notification listing;
- own-notification deletion rules;
- admin listing;
- admin create/update/delete commands;
- serialization.

Admin audit records are written through
`platform/observability.write_operation_log()`, keeping the notification write
and its audit row in one caller transaction without importing `OperationLog`
ORM into the module or router.

Both:

- `routers/notifications.py`
- `routers/admin/notifications.py`

are now ORM-free and consume the Notifications public contract.

Architecture debt ratchets from 76 to 71:

- module legacy imports: 17 -> 16;
- router ORM imports: 59 -> 55.

## N2 — producer/event boundary

Next, find legacy business producers that still instantiate
`cloudsite.models.Notification` directly and migrate them to either:

1. a Notifications public command contract, or
2. a domain event consumed by Notifications.

Catalog-release and submission-review notification flows are the first
candidates because they already have dedicated behavior tests.

## Invariants

- no notification table/schema change;
- legacy Notification imports keep exact class identity;
- users see global + own enabled, unexpired notifications only;
- users may delete only notifications addressed to themselves;
- admin create/update/delete payload semantics remain unchanged;
- re-enabling an admin notification refreshes `published_at`;
- audit rows remain atomic with admin notification commands;
- no new architecture debt IDs.
