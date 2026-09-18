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

## M4b-4a — Folder repository port and adapter

Status: implemented in this change.

Folder identity resolution now runs through `FolderIdentityRepository` and a
module-owned SQLAlchemy adapter. The port deliberately exposes no commit method,
so the legacy caller still owns the transaction exactly as before.

## M4b-4b — Descendant path-mutation boundary

Status: implemented in this change.

The descendant path rewrite now belongs to
`modules/indexing/infrastructure/production_store.py`, alongside the existing
Folder/Resource persistence adapter. Identity keeps only a legacy facade for
call compatibility.

The move preserves prefix-only replacement, SQL LIKE wildcard escaping,
caller-owned transactions, and unchanged result counts. No new indexing
legacy-dependency ID is introduced because the production store already owns
the existing Folder/Resource ORM dependency.

The architecture debt ratchet must stay at or below its existing baseline.

## M4c-1 — Admin query boundary

Status: implemented in this change.

Admin identity stats and candidate queries now run through an Identity
application service, repository port, and SQLAlchemy adapter. The legacy Router
keeps only authentication and HTTP parameter validation.

This removes the two tracked Router ORM debt IDs for
`routers/admin/identities.py`, allowing the architecture baseline to shrink
from 90 to 88.

## M4c-2 — Admin API/auth ownership

Next:

- introduce a real platform/security admin-auth contract;
- move the physical admin identities Router into the Identity API layer;
- preserve the existing paths, status validation, and ADMIN_REQUIRED behavior.

## M4d — Legacy migration/facade retirement

Then:

- move stable-ID migration/backup orchestration behind module/application ports;
- switch remaining consumers to module contracts;
- retire `cloudsite.identity` compatibility facades only after callers are gone.

## Invariants

Every step must preserve:

- existing stable resource/folder IDs;
- rename/move/copy matching semantics;
- resource-resolution commit behavior;
- folder-resolution caller-owned transaction behavior;
- append-only identity history;
- migration idempotence and zero legacy ID rewrites;
- admin authentication requirements.
