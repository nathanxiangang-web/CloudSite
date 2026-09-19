# Delivery Module Migration

Delivery owns redirect preparation, download lifecycle events, diagnostics, and
delivery-package behavior. Resources owns resource state and download rate-limit
state; Providers owns storage credentials and provider access.

## D1 — Download event ORM ownership

Status: implemented.

`DownloadEvent` and `DownloadDiagnostic` now live in
`modules/delivery/infrastructure/models.py`.

`cloudsite.models` re-exports the exact same class objects, preserving legacy
imports and schema metadata. No database migration is intended.

`modules/delivery/application/download_event.py` now imports the module-owned
model instead of `cloudsite.models`, removing one tracked
`module_legacy_import` and ratcheting architecture debt from 82 to 81.

The existing event writer still commits its own transaction; that behavior is
covered by a persistence regression test.

## D2 — Rate-limit ownership correction

Status: implemented.

Persistent download rate limiting now lives in:

```text
modules/resources/infrastructure/rate_limit.py
```

The Resources public contract exports the existing rate-limit API, while:

- `modules/delivery/infrastructure/rate_limit.py` is a contracts-only
  compatibility facade;
- `cloudsite.download_rate_limit` points to the Resources contract;
- Resources uses `platform/db.state_session()` and its own
  `DownloadRateLimit` ORM model;
- Delivery no longer imports legacy `cloudsite.database` or
  `cloudsite.models` for rate limiting.

The migration preserves the existing striped in-process locks,
`BEGIN IMMEDIATE` SQLite serialization, commit behavior, restart persistence,
cleanup rules, trusted-proxy handling, and public payload shape.

This removes two tracked module debt IDs and ratchets architecture debt from
81 to 79.

## D3 — Delivery package legacy service boundary

Next, move delivery-package service/model ownership out of
`services/delivery.py` and thin the admin/public delivery routers. Keep this
separate from the download redirect path so package behavior can be migrated
without destabilizing public downloads.

## Invariants

- no schema changes;
- no download endpoint behavior changes;
- event writes keep current commit semantics;
- rate-limit counters survive process restarts;
- rate-limit concurrency semantics remain unchanged;
- no new architecture debt IDs.
