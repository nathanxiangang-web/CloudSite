# Shares Module

## Responsibility

Share links, share tickets, share scope, and share page rendering. This module
lets a user share a resource, folder, or collection via a link with an optional
password and expiry. It validates share access, enforces scope (what the share
covers), and renders the share landing page. Downloads via a share use a 302
redirect to AList, same as authenticated downloads.

Core duties:
- Share CRUD (create, update, revoke, list).
- Share ticket validation (password, expiry, attempt limiting).
- Scope checking: does this share cover this resource?
- Share page rendering for the landing UI.
- Download redirect via share token (302 to AList entry).

## Public API

- `create_share(user_id, target, scope, password, expires_at)` - new share.
- `validate_ticket(token, password)` - validate access, return scope.
- `check_scope(share_id, resource_id)` - is resource in share scope?
- `resolve_share_download(token, resource_id)` - 302 target via share.
- `revoke_share(share_id)` - invalidate immediately.

Exports live in `contracts/public.py`.

## Domain Model

- Share (id, owner_id, target_kind, target_id, scope, password_hash, expires_at)
- ShareTicket (token, share_id, created_at, ip)
- ShareScope (share_id, resource_ids or folder_id or collection_id, recursive)
- ShareVerifyAttempt (share_id, ip, at, success) - brute-force tracking.

## Database Tables

- `shares` - share records.
- `share_verify_attempts` - brute-force attempt tracking.

Share tickets are stateless tokens (HMAC-signed), not stored in DB. Share
scope is stored as part of the share row or in a scope table for large scopes.

## Dependencies

- platform/db
- platform/security (HMAC token signing, password hashing)
- modules/identity (via contracts) - to resolve stable resource IDs in scope.
- modules/resources (via contracts) - to resolve download entries.
- modules/collections (via contracts) - when sharing a collection.

## Events/Tasks

- Emits `share.created`, `share.accessed`, `share.revoked`, `share.expired`.
- No background tasks; expiry is checked lazily on validation.
- Brute-force detection may emit a `share.brute_force_suspected` event.

## Security

- Share tokens are HMAC-signed, unguessable, and stateless.
- Optional share password is hashed with platform/security, never plaintext.
- Brute-force protection: attempt counter per share+IP, exponential backoff.
- Scope is checked on every access; a share never grants more than its scope.
- Expired shares fail closed; no grace period.
- Never log share tokens or passwords.

## Failure Modes

- Brute-force on share password: attempts tracked; after threshold, share is
  temporarily locked; owner notified.
- Scope references deleted resource: access returns 410 Gone.
- Token tampering: HMAC verification fails; return 401.
- AList unavailable for share download: return 502 with retry hint.

## Tests

- `tests/unit/` - token signing, scope checking, expiry, brute-force counter.
- `tests/contract/` - public API stability.
- Target coverage: create, validate, scope enforcement, revoke, expiry.

## Do Not

- Do not store share tokens in the database; they are stateless HMAC.
- Do not grant access without scope check, even for the share owner.
- Do not proxy file bytes; share downloads are 302 redirects.
- Do not depend on modules/search or modules/catalog beyond collections.

## Current Migration Status

**Partial.** Shares now owns the `shares` and `share_verify_attempts` ORM
models under `infrastructure/models.py`, exposes persistence-neutral
`ShareView` lifecycle operations through `contracts/public.py`, and the
public/user/admin share routers no longer import SQLAlchemy or shared ORM
models directly.

P2a moves brute-force verification-attempt persistence behind the Shares
public contract. The public verify route now records/checks/clears attempt
state through module-owned application code, scheduled verification cleanup
also uses the module contract, and the legacy service keeps only thin
configuration-aware wrappers for compatibility.

The remaining production compatibility edge is target/scope resolution
(resource/folder/collection publication checks plus share target/download
assembly). That work is intentionally separate because it must compose the
Resources, Collections and Providers owner contracts rather than moving their
ORM into Shares.
