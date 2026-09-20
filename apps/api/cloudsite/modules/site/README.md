# Site module

## Responsibility
Owns the `site_settings` table and the stable settings projections used by public Site, admin Site, Home, registration policy, Setup and share-page branding.

## Public API
Use `contracts/public.py`. Callers receive dictionaries/scalars and never Site ORM rows.

## Database Tables
- `site_settings`

## Dependencies
- platform/db
- platform/observability

## Do Not
- Do not query Resources, Providers or Presentation here. Public `/api/site` composition belongs at the app/router edge.
- Do not move share-image file bytes into the database.

## Current Migration Status
Partial: `cloudsite.site` and `cloudsite.models.SiteSettings` remain compatibility surfaces while production persistence is module-owned.
