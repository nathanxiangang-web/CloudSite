# Collections Module

## Responsibility
User collections, collection topics, collection seeds.

## Public API
- Collection CRUD, topic management, seed generation

## Domain Model
- Collection, CollectionTopic, CollectionItem

## Database Tables
- collections, collection_topics, collection_items

## Dependencies
- platform/db
- modules/catalog (via contracts)

## Current Migration Status
Code in `services/collections.py`, `services/collection_seeds.py`. To be moved in Phase 3.
