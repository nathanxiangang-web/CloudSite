# Collections Module

## Responsibility

User collections, collection topics, and collection seeds. A collection is a
user-curated group of catalog entries or resources. Topics tag collections for
discovery, and seeds are auto-generated collection starters from a seed
resource or topic. This module owns the collection lifecycle and its items.

Core duties:
- Collection CRUD (create, update, delete, list).
- Add/remove items in a collection (catalog entries or resources).
- Topic management and collection-to-topic tagging.
- Seed generation: produce a starter collection from a seed.
- Collection visibility (private, unlisted, shared via shares).

## Public API

- `create_collection(user_id, name, visibility)` - new collection.
- `add_item(collection_id, entry_id)` / `remove_item(...)`.
- `list_collections(user_id, filter)` - user's collections.
- `manage_topics(collection_id, topics)` - assign topics.
- `generate_seed(seed_resource_id, strategy)` - auto-build a collection.

Exports live in `contracts/public.py`.

## Domain Model

- Collection (id, user_id, name, visibility, created_at)
- CollectionItem (collection_id, entry_id, added_at, order)
- CollectionTopic (collection_id, topic)
- CollectionSeed (id, seed_resource_id, strategy, generated_collection_id)

## Database Tables

- `collections` - collection records.
- `collection_items` - items in each collection.
- Collection topics and seeds use tables managed here (see migrations).

## Dependencies

- platform/db
- modules/catalog (via contracts) - to validate and link catalog entries.
- modules/identity (via contracts) - to resolve resource IDs for seeds.

Collections does not depend on search or shares directly; shares references
collections when a collection is shared.

## Events/Tasks

- Emits `collection.created`, `collection.item_added`, `collection.item_removed`.
- Seed generation may enqueue a task for large seed strategies.
- No scheduled tasks; collection operations are user-initiated.

## Security

- Collection visibility enforced on every read: private = owner only,
  unlisted = link holders, shared = via shares module scope.
- A user can only modify their own collections; admin can delete any.
- Seed generation does not expose other users' private entries.

## Failure Modes

- Referenced entry deleted: item marked `entry_gone`; owner removes or ignores.
- Seed strategy fails (not enough related entries): returns partial result.
- Concurrent item add: optimistic ordering; conflicts resolved by reordering.

## Tests

- `tests/unit/` - visibility checks, item ordering, seed strategy.
- `tests/contract/` - public API stability.
- Target coverage: CRUD, visibility enforcement, seed generation.

## Do Not

- Do not store catalog metadata here; reference entries by ID.
- Do not bypass visibility checks in list queries.
- Do not depend on modules/shares; shares depends on collections, not reverse.
- Do not auto-share generated seeds; leave visibility to the owner.

## Current Migration Status

Code is currently in `services/collections.py` and
`services/collection_seeds.py`. These move to `modules/collections/` in Phase
3. The module skeleton exists with empty layers. Topic and seed tables will be
defined in the module's own migrations during the move.