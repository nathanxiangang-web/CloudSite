# Presentation

## Responsibility

Own site presentation presets, theme tokens, navigation, home-block ordering,
revision history, enable/disable state, and rollback semantics.

## Public API

Use `contracts/public.py`. It exposes validated configuration types plus admin
lifecycle operations and a persistence-neutral public presentation projection.

## Domain Model

`PresentationConfig` contains a preset, theme tokens, navigation entries and
home blocks. Built-in software/tutorial presets are validated by the same
schema used for custom configuration.

## Database Tables

- `site_presentation`
- `site_presentation_revisions`

## Dependencies

- `platform/db`
- `platform/observability`

## Events / Tasks

No background task is required. Admin mutations write operation audit records.

## Security

Presentation values are structured data only. They are validated and serialized
as JSON; no stored value is evaluated as code.

## Failure Modes

Unknown presets and missing rollback revisions are explicit application errors.
Invalid stored JSON falls back through the validated configuration parser.

## Tests

Cover preset application, save/revision creation, rollback, toggle defaults and
the public projection.

## Do Not

- Do not query Presentation ORM from routers or other modules.
- Do not write revision rows outside the Presentation application service.
- Do not import legacy `services.presentation` from this module.

## Current Migration Status

**Partial.** Admin presentation lifecycle and ORM ownership live here. Legacy
`services/presentation.py` remains only as a compatibility facade while
public Site/Home and setup call sites migrate to the public contract.
