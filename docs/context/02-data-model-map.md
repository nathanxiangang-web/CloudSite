# AI Context Pack: Data Model Map

Purpose: map every database table to its owning module so an AI agent knows
which module to touch for a given table. CloudSite has two databases:
state.db (authoritative) and index.db (rebuildable).

## state.db - Authoritative Tables

### identity module
| Table | Role |
|-------|------|
| resource_identities | canonical stable ID mapping |
| resource_identity_history | fingerprint change audit log |
| resource_identity_candidates | pending reconciliation candidates |
| folder_identities | folder-level stable ID mapping |
| folder_identity_histories | folder identity change log |

### users module
| Table | Role |
|-------|------|
| users | account records |
| user_sessions | active user sessions |
| admin_sessions | admin-only sessions |
| user_favorites | bookmarked resources |
| user_resource_history | recently viewed |
| user_playback_progress | media resume positions |

### providers module
| Table | Role |
|-------|------|
| alist_connections | AList instance connections and credentials |
| content_root_mappings | content root to provider path mapping |
| provider_sync_state | delta sync cursor per provider |

### resources module
| Table | Role |
|-------|------|
| folders | folder tree nodes |
| resources | file resource records |
| download_rate_limits | rate limit counters |

### indexing module
| Table | Role |
|-------|------|
| indexing_tasks | scan and inspection task records (new) |
| inventory_snapshots | snapshot metadata (new) |
| resource_skeletons | lightweight scan results (new) |
| sync_runs | (legacy, frozen, delete in Phase 4) |
| sync_root_results | (legacy, frozen) |
| sync_changes | (legacy, frozen) |
| sync_cycles | (legacy, frozen) |
| sync_cycle_items | (legacy, frozen) |
| folder_scan_state | (legacy, frozen) |

### catalog module
| Table | Role |
|-------|------|
| catalog_entries | catalog entry records |
| catalog_releases | release versions |
| catalog_assets | release assets |
| catalog_locations | release locations per provider |
| catalog_tags | tag definitions |
| catalog_tag_assignments | entry-tag links |
| catalog_relations | entry relation graph |
| catalog_revisions | metadata revision history |
| catalog_search_outbox | projection outbox for search |
| catalog_search_projection_state | projection watermark |
| catalog_favorites | user favorites on entries |
| catalog_subscriptions | user subscriptions |
| catalog_release_notifications | pending release notifications |

### collections module
| Table | Role |
|-------|------|
| collections | collection records |
| collection_items | items in each collection |

### shares module
| Table | Role |
|-------|------|
| shares | share records |
| share_verify_attempts | brute-force attempt tracking |

### submissions module
| Table | Role |
|-------|------|
| submissions | submission records with proposal payload |
| submission_reviews | review history per submission |

### notifications module
| Table | Role |
|-------|------|
| notifications | in-app notification records |
| notification_channels | per-user channel configuration |

### automation module
| Table | Role |
|-------|------|
| catalog_suggestions | AI/rule-generated metadata suggestions |
| parser_candidates | proposed parsing rules |
| parser_candidate_batches | batch processing records |
| review_suggestions | suggestion review queue |

### delivery module
| Table | Role |
|-------|------|
| delivery_jobs | delivery preparation records (new) |
| download_events | delivery event log (shared with resources) |
| download_diagnostics | failed delivery diagnostics |

### platform / cross-cutting
| Table | Role |
|-------|------|
| site_settings | site-level settings |
| system_settings | system-level settings |
| operation_logs | operation audit log |
| site_presentation | site presentation config |
| site_presentation_revisions | presentation revision history |
| setup_wizard_state | setup wizard progress |
| health_check_state | health check records |
| quality_todos | quality todo items |
| quality_detection_runs | quality detection runs |
| content_feedback | user content feedback |
| ai_provider_configs | AI provider configs (plugins) |
| ai_generation_drafts | AI generation drafts (plugins) |
| ai_budget_usage | AI budget usage (plugins) |
| metric_events | metric events |

## index.db - Rebuildable Tables

### search module
| Table | Role |
|-------|------|
| fts_resources | SQLite FTS5 virtual table (rebuilt, not migrated) |
| search_query_logs | query analytics for ranking tuning |

## Rules

1. A table is owned by exactly one module. That module's infrastructure/
   repository.py is the only code that writes to it.
2. Other modules read via the owning module's contracts, never directly.
3. Legacy sync_* tables are frozen; new code writes to indexing_* tables.
4. index.db tables can be dropped and rebuilt from state.db with no data loss.
5. Per-module migrations live in platform/db/migrations/ (ADR-004).
6. The 78KB legacy migrations.py splits into per-module files over Phase 3-4.

## Shared Tables Note

`download_events` and `download_diagnostics` are currently shared between
resources and delivery. During Phase 3 migration, delivery owns delivery
lifecycle events; resources owns rate limit events. The split is resolved
then.