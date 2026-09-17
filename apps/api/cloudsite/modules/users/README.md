# Users Module

## Responsibility
User accounts, sessions, authentication, admin authentication.

## Public API
- User CRUD, login/logout, session management
- Admin session creation and validation

## Domain Model
- User, UserSession, AdminSession, Role

## Database Tables
- users, user_sessions, admin_sessions, roles

## Dependencies
- platform/db
- platform/security

## Current Migration Status
Code in `auth.py`, `users.py`, `userdata.py`, `sessions.py`, `admin_auth.py`. To be consolidated in Phase 3.
