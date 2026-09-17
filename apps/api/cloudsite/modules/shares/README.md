# Shares Module

## Responsibility
Share links, share tickets, share scope, share page rendering.

## Public API
- Share CRUD, ticket validation, scope checking, share page

## Domain Model
- Share, ShareTicket, ShareScope

## Database Tables
- shares, share_tickets

## Dependencies
- platform/db
- modules/identity (via contracts)
- modules/resources (via contracts)

## Current Migration Status
Code in `shares/` subpackage (already well-structured). To be moved in Phase 3.
