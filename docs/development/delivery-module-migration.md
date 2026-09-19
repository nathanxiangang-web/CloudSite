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

Next, move `DownloadRateLimit` behavior from Delivery infrastructure into
Resources. The table is already declared as Resources-owned.

Target:

```text
download router
  -> Resources rate-limit contract/API
      -> Resources rate-limit infrastructure
          -> DownloadRateLimit ORM
```

Delivery may retain a compatibility re-export temporarily, but it must not own
the table or import Resources infrastructure internals.

This should remove the two remaining Delivery rate-limit legacy debt IDs:

- `cloudsite.database`
- `cloudsite.models`

## Invariants

- no schema changes;
- no download endpoint behavior changes;
- event writes keep current commit semantics;
- rate-limit counters survive process restarts;
- rate-limit concurrency semantics remain unchanged;
- no new architecture debt IDs.
