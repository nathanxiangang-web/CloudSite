# Search Module

## Responsibility
Full-text search, search projection, search index recovery.

## Public API
- search(query, filters) — full-text search
- recover_index() — index recovery

## Domain Model
- SearchQuery, SearchResult, SearchProjection

## Database Tables
- fts_resources (SQLite FTS5)

## Dependencies
- platform/db
- modules/resources (via contracts)

## Current Migration Status
Code in `search.py`, `services/catalog_search*.py`. To be moved in Phase 3.
