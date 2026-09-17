# Identity Module

## Responsibility

Stable resource identity generation, fingerprinting, and legacy ID migration.
This module is the single source of truth for mapping a provider object to a
stable CloudSite resource ID. When a file moves, is renamed, or is re-scanned,
the identity layer keeps the resource ID stable so that shares, favorites, and
playback progress continue to resolve.

Core duties:
- Generate 128-bit random stable resource IDs.
- Compute fingerprints (path + provider + size + mtime) for identity matching.
- Reconcile identity candidates when a provider reports a changed object.
- Track identity history for audit and rollback.
- Migrate legacy integer IDs to the new stable ID space.

## Public API

- `generate_resource_id()` - 128-bit random stable ID (URL-safe base32).
- `fingerprint(path, provider_id, size, mtime)` - deterministic fingerprint.
- `resolve_identity(provider_id, object_id)` - find existing stable ID.
- `reconcile_candidate(candidate)` - promote or reject an identity candidate.
- `migrate_legacy_id(legacy_id)` - map old integer ID to stable ID.

All exports live in `contracts/public.py`. Other modules must import from
there only, never from `domain/` or `infrastructure/`.

## Domain Model

- ResourceIdentity (resource_id, provider_id, object_id, fingerprint, first_seen, last_seen)
- FolderIdentity (folder_id, provider_id, object_id, fingerprint)
- IdentityCandidate (resource_id, candidate_fingerprint, confidence, status)
- IdentityHistory (resource_id, old_fingerprint, new_fingerprint, changed_at, reason)

## Database Tables

- `resource_identities` - canonical stable ID mapping.
- `resource_identity_history` - fingerprint change audit log.
- `resource_identity_candidates` - pending reconciliation candidates.
- `folder_identities` - folder-level stable ID mapping.
- `folder_identity_histories` - folder identity change log.

## Dependencies

- platform/db (sessions, unit of work)
- platform/observability (structured logging)
- modules/providers (via contracts) - to read provider object metadata.

No dependency on resources, catalog, or shares. Identity is a leaf domain.

## Events/Tasks

- Emits `identity.reconciled` when a candidate is promoted.
- Emits `identity.conflict` when two candidates claim one stable ID.
- Consumes `provider.object_changed` from the providers module.
- No long-running tasks; reconciliation is synchronous within indexing scans.

## Security

- Resource IDs are unguessable 128-bit random values (no enumeration).
- Fingerprint inputs are provider-supplied; treat as untrusted data.
- Identity history is append-only; deletions require admin audit.
- No PII stored in identity records.

## Failure Modes

- Fingerprint collision (two distinct objects, same fingerprint): resolved by
  confidence scoring and manual review via identity candidates.
- Provider reports stale mtime: fingerprint may mismatch; candidate queue
  absorbs the ambiguity until next scan.
- Legacy ID migration gap: a legacy ID with no stable counterpart returns a
  tombstone until backfill completes.

## Tests

- `tests/unit/` - fingerprint determinism, ID format, candidate scoring.
- `tests/contract/` - public API stability contract tests.
- Target coverage: identity resolution paths, candidate promotion, conflict.

## Do Not

- Do not store business metadata (title, tags) here; that belongs to catalog.
- Do not depend on modules/resources or modules/shares.
- Do not reuse provider object IDs as stable IDs; always generate a new ID.
- Do not delete identity rows on fingerprint change; write history instead.

## Current Migration Status

Existing code lives in the top-level `identity/` subpackage. The module
skeleton under `modules/identity/` is in place with empty layers. Migration to
`modules/identity/` is scheduled for Phase 3, first in the module move order
because shares, resources, and catalog all depend on stable IDs.