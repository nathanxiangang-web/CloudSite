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

## M4b-2 — Persistence-free matching core

Status: implemented in this change.

Resource fingerprint candidate policy now lives in
`modules/identity/application/matching.py`, while path normalization/event
classification lives in the domain layer. The legacy SQLAlchemy service
delegates matching decisions to this pure code but retains transactions,
allocation, history writes, and audit side effects.

## M4b-3 — Resource repository port and adapter

Status: implemented in this change.

Resource identity resolution now runs from the module application layer through
`ResourceIdentityRepository` and `IdentityAuditSink` ports. The SQLAlchemy
adapter owns module ORM access. The legacy compatibility service injects an
OperationLog audit sink backed by the caller's same AsyncSession, preserving
single-transaction history/audit writes and the resolver's one final commit.

## M4b-4 — Folder repository port

Status: implemented in this change.

Folder identity resolution now runs through a module-owned
`FolderIdentityRepository` adapter. Unlike resource resolution, the folder
port deliberately exposes no commit operation, preserving the existing
caller-owned transaction behavior.

The legacy `cascade_rename_descendants()` helper is intentionally not moved
into Identity: it mutates index-owned Folder/Resource rows. A later indexing/
resource boundary change must own that mutation rather than creating an
Identity dependency on shared legacy models.

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
