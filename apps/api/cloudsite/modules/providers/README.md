# Providers Module

## Responsibility
Storage provider abstraction, AList client, provider capabilities, delta sync support.

## Public API
- ProviderRegistry, ProviderCapability
- AListClient (storage gateway)

## Domain Model
- Provider, Connection, ContentRootMapping, ProviderCapability

## Database Tables
- connections, content_root_mappings

## Dependencies
- platform/db
- platform/http

## Current Migration Status
Code in `providers/` subpackage and `alist.py`. Already well-structured.
