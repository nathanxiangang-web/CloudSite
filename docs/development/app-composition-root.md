# App Composition Root

CloudSite 2.0 now uses cloudsite/infrastructure/composition.py as the explicit
FastAPI composition root.

## Why this exists

The legacy cloudsite.main module historically mixed FastAPI object creation,
middleware and exception registration, public router wiring, admin router
wiring, plugin discovery, and compatibility re-exports. That made main.py a
high-conflict file and encouraged new features to wire themselves directly into
a legacy global module.

M3 moves the application graph out of main.py without changing business
behavior.

## Two-phase composition

Composition is intentionally split into two functions.

1. create_app_shell()
   - creates FastAPI;
   - installs lifespan;
   - installs middleware;
   - installs exception handlers.
2. compose_app(app)
   - registers public/user routers;
   - registers admin/platform routers;
   - loads enabled plugins and registers plugin routers.

main.py now performs only these two composition calls:

    app = create_app_shell()
    _registry = compose_app(app)

The two phases preserve a legacy compatibility detail: cloudsite.main.app exists
before router modules are imported. This reduces circular-import risk while the
1.x compatibility surface is still being removed.

## Compatibility surface

M3 deliberately keeps historical re-exports still used by tests and legacy
code, including scheduler state, selected router helpers/caches, DTO helpers,
and security/database functions.

Those re-exports are migration debt, not the target architecture. Remove them
incrementally only when callers have moved behind module or platform contracts.

## Rule for new work

New feature code must not add router wiring to cloudsite.main. Add or remove
application wiring in the composition layer. Business logic still belongs in
the owning module; the composition root only assembles concrete components.

Architecture tests enforce that main.py contains no direct include_router calls
and no router imports.

## Next step

After M3, the next high-value migration is a complete golden business module.
Identity is a strong candidate: domain, application, infrastructure, contracts,
and API inside one module, with legacy adapters at the edge instead of
shared-core imports.
