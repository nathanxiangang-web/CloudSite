# Identity Module

## Responsibility
Stable resource ID generation, fingerprinting, and legacy ID migration.

## Public API
- `generate_resource_id()` — 128-bit random stable ID
- `fingerprint(path, provider_id)` — resource fingerprint for identity matching

## Domain Model
- ResourceIdentity (resource_id, provider_id, object_id, fingerprint)

## Database Tables
- resource_identities

## Dependencies
- platform/db
- modules/providers (via contracts)

## Current Migration Status
Existing code in `identity/` subpackage. To be moved to `modules/identity/` in Phase 3.
