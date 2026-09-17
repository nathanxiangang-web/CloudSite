# Resources Module

## Responsibility
Resource domain: folders, files, previews, downloads, download rate limiting, office document handling.

## Public API
- Resource detail, folder browse, preview, download redirect

## Domain Model
- Folder, Resource, ResourceFile, Preview

## Database Tables
- folders, resources, resource_files

## Dependencies
- platform/db
- modules/providers (via contracts)
- modules/identity (via contracts)

## Current Migration Status
Code in `indexer.py`, `preview.py`, `download.py`, `download_rate_limit.py`, `office.py`. To be moved in Phase 3.
