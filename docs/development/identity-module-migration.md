# Identity Module Migration

Identity is the first CloudSite 2.0 golden-module migration because stable IDs
sit underneath indexing, resources, shares, collections, and user history.

The migration is deliberately incremental so stable resource IDs never change
as a side effect of architecture work.

## M4a — Pure core and public contract

Status: implemented in this change.

Moved into the business module:

- identity observation/resolution DTOs;
- resource fingerprint rule;
- folder fingerprint rule;
- public contract exports.

Legacy import paths remain facades pointing at the exact same classes/functions.
No database table, transaction, ID assignment, matching, or migration behavior
changes in M4a.

## M4b-1 — ORM ownership

Status: implemented in this change.

The five identity-owned ORM classes now live in
`modules/identity/infrastructure/models.py` and use the shared platform DB
bases. `cloudsite.models` is a compatibility re-export only. Database table
names, columns, constraints, and metadata remain identical.

## M4b-2 — Application and repository ports

Next:

- define identity repository/unit-of-work ports inside the module;
- separate matching decisions from SQLAlchemy persistence;
- adapt the existing state/index database implementation behind infrastructure;
- migrate resource/folder resolution without introducing a new
  module_legacy_import debt ID.

The architecture debt ratchet must stay at or below its existing baseline.

## M4c — API and persistence ownership

Then:

- move admin identity diagnostics behind identity application queries;
- move identity-owned ORM declarations out of the shared model surface when
  metadata/migration compatibility permits;
- switch all consumers to modules/identity/contracts;
- retire cloudsite.identity compatibility facades only after callers are gone.

## Invariants

Every step must preserve:

- existing stable resource/folder IDs;
- rename/move/copy matching semantics;
- resource-resolution commit behavior;
- folder-resolution caller-owned transaction behavior;
- append-only identity history;
- migration idempotence and zero legacy ID rewrites;
- admin authentication requirements.
