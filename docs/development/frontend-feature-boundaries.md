# Frontend Feature Boundary Gate

CloudSite 2.0 treats the web application as a modular frontend, not as a single
components/lib bucket.

## Enforced now

The frontend CI architecture gate checks:

1. Every feature directory has feature.json and a public index.ts/index.tsx.
2. Feature-to-feature imports may only target the other feature's public entry.
3. app routes may import a feature public entry but not its internal files.
4. components/ui is business-agnostic and may not import any feature.
5. app/globals.css is a legacy hotspot and may shrink but may not grow beyond
   the M5 baseline of 153,299 bytes.

The globals.css size rule is a ratchet, not a claim that the existing file is
healthy. New feature-specific styles must move into the owning feature.

## Feature manifest

Example:

{
  "schema_version": 1,
  "name": "catalog",
  "migration_status": "partial",
  "public_entry": "index.ts",
  "routes": ["/catalog"]
}

Allowed migration_status values are skeleton, partial, and complete.

## Migration sequence

M5 installs the boundary and CI gate without rewriting existing pages.

M6 should migrate Catalog as the first golden feature because its code is
currently spread across app/catalog, components/catalog, lib/catalog.ts,
lib/catalog-client.ts, admin helpers, and multiple tests.

The route should become a thin composition file while Catalog owns its API
client, types, hooks, components, views, and feature styles.
