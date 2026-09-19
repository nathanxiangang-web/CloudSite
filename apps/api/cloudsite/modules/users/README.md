# Users Module

## Responsibility

User accounts, authentication, session management, and admin authentication.
This module owns the user lifecycle: registration, login, logout, role
assignment, and session validity. It also handles admin-only sessions that
have separate expiry and scope from user sessions.

Core duties:
- User CRUD and profile management.
- Password hashing and verification.
- User session creation, validation, and revocation.
- Admin session creation with elevated scope and shorter TTL.
- Role and permission checks consumed by other modules' routers.

## Public API

- `create_user(email, password)` - register a new user.
- `authenticate(email, password)` - verify credentials, return session.
- `validate_session(token)` - check session validity and load user.
- `revoke_session(token)` - logout / invalidate.
- `create_admin_session(credentials)` - elevated session for admin routes.
- `has_permission(user, scope, action)` - permission gate.

Exports live in `contracts/public.py`.

## Domain Model

- User (id, email, password_hash, role, status, created_at)
- UserSession (id, user_id, token, expires_at, ip, user_agent)
- AdminSession (id, admin_id, token, expires_at, scope)
- Role (id, name, permissions)
- UserFavorite (user_id, resource_id) - cross-module link via identity.
- UserPlaybackProgress (user_id, resource_id, position, updated_at)

## Database Tables

- `users` - account records.
- `user_sessions` - active user sessions.
- `admin_sessions` - admin-only sessions.
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
- Admin sessions have shorter TTL and separate storage from user sessions.
- Rate limiting on login is enforced in platform/http middleware.
- Never log session tokens or password hashes.

## Failure Modes

- Session store unavailable: validation fails closed (deny request).
- Password hash migration: old hashes rehashed on successful login.
- Concurrent login: multiple sessions allowed per user; revocation is per-token.
- Admin session expiry mid-operation: router returns 401, client re-auths.

## Tests

- `tests/unit/` - password hashing, token format, session validity.
- `tests/contract/` - public API stability.
- Target coverage: auth success/failure, session expiry, role checks.

## Do Not

- Do not store sessions in JWT payload; use opaque server-side sessions.
- Do not mix admin and user session tables.
- Do not depend on modules/catalog or modules/shares.
- Do not expose password_hash in any API response or log.

## Current Migration Status

Users is now **partial** rather than a skeleton.

- `User` ORM ownership moved to `infrastructure/models.py`.
- `cloudsite.models.User` remains an exact compatibility re-export.
- `contracts/public.py` exposes persistence-neutral batch user references
  (`id`, `username`, `status`) for business modules such as Submissions.
- Authentication, user/admin sessions, favorites, history, playback progress,
  and the legacy admin user routes remain follow-up migration work.
