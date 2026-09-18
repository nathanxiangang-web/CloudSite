# Frontend Features

CloudSite 2.0 business UI is migrated incrementally into feature modules.

Each feature directory must contain:

- feature.json — machine-readable migration metadata
- index.ts or index.tsx — the only public entry point
- api.ts/types.ts/hooks/components/views/styles as needed

Cross-feature imports must use the other feature's public index. App routes may
compose feature public entries but must not import feature internals.

Do not create empty feature directories just to satisfy architecture. Create a
feature when a route or business slice is actually being migrated.
