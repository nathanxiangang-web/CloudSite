# Notifications Module

## Responsibility
Notification channels (in-app, webhook).

## Public API
- Notification send/list/mark-read

## Domain Model
- Notification, NotificationChannel

## Database Tables
- notifications, notification_channels

## Dependencies
- platform/db

## Current Migration Status
Code in `services/notifications.py`, `routers/notifications.py`. To be moved in Phase 3.
