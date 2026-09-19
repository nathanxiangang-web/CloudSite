# Module Manifest

CloudSite 2.0 uses `module.yaml` as the machine-readable companion to each business module README.

## Location

Every business module must contain `module.yaml`, `README.md`, and `contracts/public.py`.

## Required fields

- `schema_version`: current value `1`.
- `name`: must equal the module directory name.
- `kind`: currently `business`.
- `migration_status`: `skeleton`, `partial`, or `active`.
- `responsibility`: one-sentence ownership boundary.
- `public_contract`: supported cross-module import surface.
- `allowed_dependencies`: platform packages and other modules' contracts.
- `owned_tables`: target ownership; physical legacy placement may differ during migration.
- `forbidden_dependencies`: dependencies that must not be introduced.
- `constraints`: module-specific non-negotiable behavior.

## Migration status

- `skeleton`: target boundary exists; running implementation is predominantly legacy.
- `partial`: meaningful production code exists in the module, but legacy dependencies or entry points remain.
- `active`: the module owns an active 2.0 path and is the default home for new work in that domain.

## Boundary rule

Another business module may import only `modules/<name>/contracts/*`. It must not import `domain/`, `application/`, `infrastructure/`, or `api/` internals.

## Machine enforcement

`scripts/check-module-architecture.py` treats every `module.yaml` as executable
architecture policy.

CI rejects:

- duplicate `owned_tables` entries across business modules;
- unknown or malformed module/platform/plugin dependencies;
- business-module dependency cycles;
- runtime imports of another module's public contract when that dependency is
  missing from `allowed_dependencies`;
- invalid manifest identity, migration status, or missing public contract files.

The manifest is therefore not a planning note or aspirational ownership map. It
must describe the dependency graph and table ownership that the repository
currently intends to preserve.

Existing legacy-core imports are governed separately by the architecture-debt
ratchet. Cross-module internal imports remain forbidden by the architecture
boundary tests.
