# Delivery Module

## Responsibility

Delivery preparation, download redirect, and delivery tracking. This module is
the final hop before a user gets bytes: it prepares a delivery (resolves the
resource, checks authorization, builds the AList entry), issues a 302 redirect,
and records the delivery event for tracking and analytics. It does not proxy
file bodies; the redirect goes directly to AList.

Core duties:
- Prepare a delivery: resolve resource, check auth, build redirect target.
- Issue 302 redirect to the AList-native download entry.
- Track delivery events (start, complete, fail) for analytics.
- Delivery diagnostics for failed downloads.
- Cache warm-up for hot resources (optional, task-driven).

## Public API

- `prepare_delivery(resource_id, user, context)` - build delivery plan.
- `resolve_redirect(delivery_id)` - 302 target URL.
- `track_event(delivery_id, event_kind)` - record delivery event.
- `get_diagnostics(delivery_id)` - failure diagnostics.

Exports live in `contracts/public.py`. The `public/` directory holds the
delivery event and plan schemas.

## Domain Model

- DeliveryJob (id, resource_id, user_id, prepared_at, status)
- DeliveryRedirect (delivery_id, target_url, expires_at)
- DeliveryEvent (delivery_id, kind, at, metadata) - start, complete, fail.
- DeliveryDiagnostics (delivery_id, error_kind, detail, at)

## Database Tables

- `delivery_jobs` - delivery preparation records (new).
- `download_events` - delivery event log (shared with resources, may split).
- `download_diagnostics` - failed delivery diagnostics.

The `download_events` and `download_diagnostics` tables are currently shared
with the resources module. During migration, delivery-specific events will be
owned here, while resource-facing rate limit events stay in resources.

## Dependencies

- platform/db
- platform/http (for building redirect URLs)
- modules/providers (via contracts) - to build the AList download entry.
- modules/resources (via contracts) - to resolve the resource and check auth.
- modules/identity (via contracts) - to resolve stable resource IDs.

## Events/Tasks

- Emits `delivery.started`, `delivery.completed`, `delivery.failed`.
- Cache warm-up enqueues a task; not inline.
- Delivery events are consumed by analytics and observability.

## Security

- Delivery requires an authenticated session or a valid share token.
- Redirect URLs are signed or scoped to prevent tampering and reuse.
- Delivery events record user ID and resource ID but no credentials.
- Diagnostics do not include full URLs with tokens; redacted.

## Failure Modes

- AList unavailable: redirect fails; return 502 with retry hint; event logged.
- Resource gone between prepare and redirect: return 410; event logged.
- Redirect URL expired: client re-prepares; old URL returns 410.
- Tracking write fails: delivery still proceeds; event logged best-effort.

## Tests

- `tests/unit/` - redirect URL building, event tracking, diagnostics.
- `tests/contract/` - delivery plan and event schema stability.
- Target coverage: prepare, redirect, track, auth enforcement, failure modes.

## Do Not

- Do not proxy file bytes; always 302 to AList.
- Do not put tokens in logged redirect URLs; redact.
- Do not depend on modules/catalog or modules/search.
- Do not block delivery on tracking writes; best-effort logging.

## Current Migration Status

Code is currently in `services/delivery.py` and `routers/delivery.py`. These
move to `modules/delivery/` in Phase 3. The module skeleton with schemas in
`public/` is in place. The split of `download_events` between resources and
delivery will be resolved during migration, with delivery owning the delivery
lifecycle events and resources owning rate limit events.

## Migration Progress

- D1 ORM ownership: `DownloadEvent` and `DownloadDiagnostic` are owned by
  `modules/delivery/infrastructure/models.py`.
- `cloudsite.models` remains a compatibility re-export for legacy callers.
- Download-event writes now import the Delivery-owned ORM directly.
- Existing event commit semantics are preserved.
- D2 rate-limit ownership: persistent download rate limiting now lives in
  Resources, the declared owner of `download_rate_limits`.
- Delivery keeps only a compatibility re-export of the Resources rate-limit
  contract; it no longer imports shared database/model layers for rate limiting.
- Next: migrate the delivery-package legacy service/router boundary.

## D3 Admin Diagnostics Boundary

Delivery now owns the admin download-diagnostic workflow in
`application/diagnostics.py`.

- Resources supplies a persistence-neutral diagnostic resource view;
- Providers supplies the runtime gateway;
- Delivery resolves the download entry, records step outcomes, persists
  `DownloadDiagnostic`, and exposes diagnostic history;
- `routers/admin/diagnostics.py` is ORM/SQLAlchemy-free and keeps only the
  historical `download_diagnostic_dict` compatibility symbol.
