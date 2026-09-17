# Catalog Module

## Responsibility
Catalog entries, metadata, follow, views, publication scope.

## Public API
- CatalogEntry CRUD, metadata extraction, follow/unfollow
- Catalog search and projection

## Domain Model
- CatalogEntry, CatalogMetadata, CatalogRelease, CatalogFollow

## Database Tables
- catalog_entries, catalog_metadata, catalog_releases, catalog_follows

## Dependencies
- platform/db
- modules/resources (via contracts)
- modules/search (via contracts)

## Current Migration Status
Code in `services/catalog*.py` (46.8KB — largest service file). To be split and moved in Phase 3.
