# Notifications Module

## Responsibility

Notification channels and delivery. This module sends and stores
notifications for users: in-app notifications and webhook notifications. It is
the fan-out point for events from other modules (catalog release, submission
review outcome, share brute-force alert). Notifications are persisted so users
can view history and mark read.

Core duties:
- Send a notification via one or more channels.
- Store notifications for in-app history.
- List and mark-read for a user.
- Webhook delivery with retry (via platform/tasks).
- Channel configuration per user (opt-in/opt-out).

## Public API

- `send_notification(user_id, kind, payload, channels)` - enqueue send.
- `list_notifications(user_id, filter, page)` - in-app history.
- `mark_read(notification_id)` / `mark_all_read(user_id)`.
- `configure_channel(user_id, channel, enabled)` - opt-in/out.

Exports live in `contracts/public.py`.

## Domain Model

- Notification (id, user_id, kind, payload, read_at, created_at)
- NotificationChannel (user_id, channel, enabled, config)
- NotificationKind (catalog_release, submission_review, share_alert, ...)

## Database Tables

- `notifications` - in-app notification records.
- `notification_channels` - per-user channel configuration.

Webhook delivery attempts are tracked via platform/tasks retry records, not a
separate table here.

## Dependencies

- platform/db
- platform/tasks (for webhook delivery with retry)
- platform/http (for outbound webhook HTTP calls)
- platform/observability

Notifications does not depend on any business module directly; it consumes
events emitted by other modules. This keeps the dependency direction clean:
catalog, submissions, and shares emit events; notifications consumes them.

## Events/Tasks

- Consumes `catalog.release_published`, `submission.reviewed`,
  `share.brute_force_suspected`, and other domain events.
- Enqueues webhook delivery tasks with retry.
- Emits `notification.sent`, `notification.read` for analytics.

## Security

- A user can only list and mark-read their own notifications.
- Webhook URLs are user-configured and validated; no SSRF to internal IPs.
- Webhook payloads contain no secrets; only event metadata.
- Channel config is per-user; admin cannot read a user's notification payload.

## Failure Modes

- Webhook unreachable: task retries with exponential backoff; after max
  retries, the webhook is marked failing and the user notified in-app.
- Notification payload too large: truncated with a `truncated` flag.
- High fan-out volume: send is async via tasks; no inline fan-out blocking.
- User deleted: notifications orphaned and cleaned up lazily.

## Tests

- `tests/unit/` - channel routing, payload truncation, mark-read logic.
- `tests/contract/` - public API stability.
- Target coverage: send, list, mark-read, webhook retry, channel config.

## Do Not

- Do not depend on catalog, submissions, or shares directly; consume events.
- Do not send webhooks inline; always via tasks.
- Do not include secrets in webhook payloads.
- Do not allow reading another user's notifications.

## Current Migration Status

Code is currently in `services/notifications.py` and
`routers/notifications.py`. These move to `modules/notifications/` in Phase 3.
The module skeleton exists with empty layers. The event consumer wiring will
be set up during migration, connecting to the platform event bus.