# Users Module

## Responsibility

Users owns user accounts, public/user authentication persistence, server-side
user sessions, roles/permissions, favorites, resource history, and playback
progress.

Administrator authentication is a separate runtime mechanism. The current code
does **not** have an `AdminSession` ORM model or an `admin_sessions` table, so
that mechanism is not a pending ORM migration simply because older design text
described one.

Core duties:
- User CRUD and profile/account management.
- Password hashing/verification and registration/login/logout/password change.
- Opaque server-side user-session creation, validation, revocation, and cleanup.
- Administrator user management and role/permission policy.
- Favorites, resource history, and playback-progress persistence.

## Public Contract

`contracts/public.py` exposes the current module boundary, including:

- authentication workflows: `register_user`, `login_user`, `logout_user`,
  `change_user_password`;
- user-session state: create/resolve/validate/revoke/cleanup operations;
- administrator user-management operations;
- role/permission policy and role-management operations;
- persistence-neutral user references;
- favorites/history/playback-progress operations.

HTTP cookie/request shims may remain outside the module while persistence and
business policy stay module-owned.

## Persistence

Users owns these ORM tables through `infrastructure/models.py`:

- `users`
- `user_sessions`
- `user_favorites`
- `user_resource_history`
- `user_playback_progress`

There is currently **no** `admin_sessions` table.

## Administrator Authentication — Current Runtime

Administrator login/session validation currently uses
`cloudsite/infrastructure/security.py`:

- `create_session_token(username)` creates a signed token containing the
  username and expiry;
- `verify_session_token(token)` validates an HMAC-SHA256 signature and expiry;
- the maximum age is `ADMIN_SESSION_MAX_AGE_SECONDS = 7 days`;
- the token is signed with `settings.secret_key`;
- no administrator session row is stored server-side, so there is no
  per-session database revocation record today.

This is intentionally documented as the current runtime, not as a target
architecture. If product/security requirements later need administrator
per-device sessions, server-side revocation, or administrator-session audit
lifecycle, that should be designed as a separate change with explicit
requirements and migration work.

## Dependencies

- platform/db
- platform/security
- platform/http
- platform/observability
- modules/identity contracts where stable resource identity is required

## Security

- Password hashes never leave the Users boundary in API responses or logs.
- Public/user sessions use opaque server-side session records rather than JWT
  payload state.
- Administrator authentication currently uses the separate signed-cookie
  mechanism described above; do not pretend it has server-side session
  revocation semantics that do not exist.
- Session tokens, signed administrator tokens, and password hashes must not be
  logged.
- New cross-module consumers should use `contracts/public.py`, not Users
  internals.

## Failure Modes

- Invalid/revoked/expired user session: validation fails closed.
- Invalid/expired administrator signed token: administrator authentication
  fails and the client must authenticate again.
- Disabled/deleted users are rejected by the Users-owned authentication/session
  workflows.
- Session cleanup failure must not make an invalid session valid.

## Current Migration Status

Users is **partial** because compatibility/HTTP surfaces remain, not because a
new administrator-session table is required.

Completed ownership:
- `User` and `UserSession` ORM ownership is in
  `modules/users/infrastructure/models.py`;
- server-side user-session create/validate/revoke/cleanup is behind the Users
  contract; `cloudsite.sessions` is an HTTP/compatibility shim;
- registration/login/logout/password-change persistence and audit live in
  `application/authentication.py`;
- username/password rules live in `domain/credentials.py`;
- administrator user CRUD/status/password-reset workflows live in
  `application/admin_management.py`;
- role/permission policy and persistence workflows are Users-owned;
- favorites, resource history, and playback-progress persistence is
  Users-owned.

Current stop point:
- do **not** create `AdminSession`/`admin_sessions` merely to match historical
  README text;
- revisit administrator session persistence only when a concrete
  security/product requirement such as revocation or session inventory makes
  it useful;
- remaining compatibility facades should be reduced only after caller-zero or
  when they create measurable maintenance risk.
