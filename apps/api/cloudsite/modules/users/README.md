# Users Module

## Responsibility

User accounts, authentication, session management, and admin authentication.
This module owns the user lifecycle: registration, login, logout, role
assignment, and session validity. Administrator authentication currently uses
a separate signed-cookie runtime mechanism rather than an AdminSession ORM.

Core duties:
- User CRUD and profile management.
- Password hashing and verification.
- User session creation, validation, and revocation.
- Keep administrator authentication separate from server-side user sessions; the current administrator token is a 7-day HMAC-signed cookie with no admin-session table.
- Role and permission checks consumed by other modules' routers.

## Public API

- `create_user(email, password)` - register a new user.
- `authenticate(email, password)` - verify credentials, return session.
- `validate_session(token)` - check session validity and load user.
- `revoke_session(token)` - logout / invalidate.
- `has_permission(user, scope, action)` - permission gate.

Exports live in `contracts/public.py`.

## Domain Model

- User (id, email, password_hash, role, status, created_at)
- UserSession (id, user_id, token, expires_at, ip, user_agent)
- Role (id, name, permissions)
- UserFavorite (user_id, resource_id) - cross-module link via identity.
- UserPlaybackProgress (user_id, resource_id, position, updated_at)

## Database Tables

- `users` - account records.
- `user_sessions` - active user sessions.
- `user_favorites` - bookmarked resources.
- `user_resource_history` - recently viewed.
- `user_playback_progress` - media resume positions.

## Dependencies

- platform/db
- platform/security (token generation, password hashing, crypto)
- platform/http (request context for session extraction)
- modules/identity (via contracts) - to resolve favorited resource IDs.

## Events/Tasks

- Emits `user.registered`, `user.login`, `user.logout`.
- Emits `user.role_changed` when admin reassigns roles.
- No background tasks; session cleanup is lazy on validation.

## Security

- Passwords hashed with platform/security (argon2 or bcrypt, never plaintext).
- Session tokens are opaque random values, not JWTs with payload.
- Administrator authentication currently uses a 7-day HMAC-SHA256 signed token (`infrastructure/security.py`) and has no server-side AdminSession row.
- Rate limiting on login is enforced in platform/http middleware.
- Never log session tokens or password hashes.

## Failure Modes

- Session store unavailable: validation fails closed (deny request).
- Password hash migration: old hashes rehashed on successful login.
- Concurrent login: multiple sessions allowed per user; revocation is per-token.
- Administrator signed-token expiry mid-operation: router returns 401, client re-auths.

## Tests

- `tests/unit/` - password hashing, token format, session validity.
- `tests/contract/` - public API stability.
- Target coverage: auth success/failure, session expiry, role checks.

## Do Not

- Do not store sessions in JWT payload; use opaque server-side sessions.
- Do not invent an `admin_sessions` table solely to match historical design text; add administrator session persistence only for a concrete security/product requirement such as revocation or session inventory.
- Do not depend on modules/catalog or modules/shares.
- Do not expose password_hash in any API response or log.

## Current Migration Status

Users is now **partial** rather than a skeleton.

- `User` ORM ownership moved to `infrastructure/models.py`.
- `cloudsite.models.User` remains an exact compatibility re-export.
- `contracts/public.py` exposes persistence-neutral batch user references
  (`id`, `username`, `status`) for business modules such as Submissions.
- `UserSession` ORM and server-side session create/validate/revoke/cleanup
  now live behind the Users contract; `cloudsite.sessions` is an HTTP/
  compatibility shim for cookies and request metadata.
- Public registration/login/logout/password-change persistence and audit
  now live in `application/authentication.py`; root `cloudsite.auth` is
  the HTTP/origin/cookie compatibility edge.
- Username/password input rules now live in `domain/credentials.py`.
- Administrator user list/create/rename/status/password-reset/soft-delete
  workflows now live in `application/admin_management.py`; root
  `cloudsite.users` is an HTTP/query edge with no ORM access.
- Favorites, resource history, and playback-progress ORM + persistence now
  live in `application/user_data.py`; root `cloudsite.userdata` composes
  visible resources through Resources/Providers contracts.
- Administrator session persistence is **not** an automatic follow-up: current admin auth uses a separate 7-day HMAC-signed cookie with no `AdminSession` ORM/`admin_sessions` table. Revisit only for a concrete revocation, session-inventory, audit, or related security/product requirement.

## Role Policy Ownership

Users now owns team role and permission policy in `domain/roles.py` and
role persistence workflows in `application/role_management.py`.

- role validation, hierarchy and permission mapping are Users domain policy;
- admin user-role listing and role updates are Users application workflows;
- `services/roles.py` is a compatibility shim for legacy callers;
- `routers/admin/roles.py` contains no direct ORM/SQLAlchemy access.
