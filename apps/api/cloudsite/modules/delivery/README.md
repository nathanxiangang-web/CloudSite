# Delivery Module

## Responsibility
Delivery preparation, download redirect, delivery tracking.

## Public API
- Delivery prepare/track, download redirect

## Domain Model
- DeliveryJob, DeliveryRedirect

## Database Tables
- delivery_jobs

## Dependencies
- platform/db
- modules/providers (via contracts)
- modules/resources (via contracts)

## Current Migration Status
Code in `services/delivery.py`, `routers/delivery.py`. To be moved in Phase 3.
