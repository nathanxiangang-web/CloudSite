# Indexing Module (v2)

## Responsibility
Inventory scan, resource inspection, snapshot reconciliation. Replaces legacy rolling sync.

## Public API
- scan_category(content_root, category) — inventory scan
- inspect_resource(resource_id) — detail inspection
- reconcile_snapshot(snapshot) — reconcile with DB

## Domain Model
- InventorySnapshot, ResourceSkeleton, InspectionResult, ChangeRecord

## Database Tables
- (new) indexing_tasks, inventory_snapshots, resource_skeletons

## Dependencies
- platform/db
- platform/tasks
- modules/providers (via contracts)
- modules/resources (via contracts)

## Current Migration Status
NEW module. Legacy `sync/rolling.py` is frozen. New code goes here.
