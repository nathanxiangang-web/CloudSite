# work02 D1 资源级检索 - 交付结果

## 修改文件列表

### 后端（apps/api）
- `cloudsite/models.py`：新增 `CatalogSearchOutbox`（state.db 投影 outbox 表）与 `CatalogSearchProjectionState`（index.db 投影水位表）ORM 模型。
- `cloudsite/migrations.py`：新增 `state_v7_to_v8_upgrade` 迁移（建 `catalog_search_outbox` 表 + 索引），`CURRENT_SCHEMA_VERSION` 提升至 8，注册到迁移链。
- `cloudsite/database.py`：`init_databases` 中在 index.db 创建 `catalog_search_fts`（FTS5，与旧 `search_fts` 分离）与 `catalog_search_projection_state` 表。
- `cloudsite/services/catalog_search_projection.py`（新增）：D1 投影核心。包含 `enqueue_catalog_search_outbox`（业务同事务入队）、`consume_catalog_search_outbox`（消费者：水位保护、旧 revision 跳过、upsert/delete 投影、确认回写）、`rebuild_catalog_search_index`（全量重建）、`catalog_search_fts_match`（FTS 召回）。
- `cloudsite/services/catalog.py`：在 `create_catalog_entry`/`update_catalog_entry`/`publish_catalog_entry`/`attach_catalog_location` 末尾同事务 enqueue outbox。
- `cloudsite/services/catalog_metadata.py`：在 tag 分配/移除/更新/删除后为受影响 entry enqueue outbox。
- `cloudsite/services/catalog_search.py`：改造 `search_published_catalog` 为 FTS 查询——先消费 outbox，再 `catalog_search_fts` MATCH 召回，content_type/tag/platform 过滤，`catalog_entry_view` fail-closed 实时校验，无结果时返回 `suggestion` 文案。
- `cloudsite/routers/admin/search.py`：新增 `POST /api/admin/catalog/search/rebuild` 全量重建端点。
- `tests/test_catalog_search_service.py`：重写为 8 个测试覆盖 FTS 投影、fail-closed、outbox 幂等重放、旧不覆盖新、重建、空查询、无结果反馈、content_type 过滤。
- `tests/test_catalog_c3_metadata_migration.py`、`tests/test_catalog_release_asset_schema.py`：版本断言更新为 8。

### 前端（apps/web）
- `src/lib/catalog.ts`：新增 `CatalogSearchItem`/`CatalogSearchResponse` 类型与 `buildCatalogSearchQuery`。
- `src/lib/catalog-client.ts`：新增 `fetchCatalogSearch`。
- `src/app/search/page.tsx`：全局搜索页增加"资源条目"分区（条目卡命中 `/catalog/{entry_id}`，文件命中保持旧文件页），类型标识清晰；无结果时统一提示。
- `src/app/catalog/page.tsx`：目录页增加搜索框接入 `/api/catalog/search`，有 query 时显示搜索结果，无 query 时保持原列表。

## 核心改动

### ProjectionOutbox 模式（跨库一致性）
- state.db `catalog_search_outbox`：业务写操作同事务入队（entry_id, revision, action）。
- index.db `catalog_search_projection_state`：水位表（entry_id, applied_revision）。
- 消费者（读路径同步触发）：按 created_at 升序处理 pending 行，在同一 index 事务更新 FTS + 水位，确认后回写 state `consumed_at`。
- 崩溃重放幂等：`applied_revision >= outbox.revision` 的行跳过。
- 旧 revision 不覆盖新数据：`entry.revision > outbox.revision` 的行跳过。

### FTS 投影
- 独立 `catalog_search_fts` 表（不修改旧 `search_fts`），字段：entry_id, content_type, title, summary, description, aliases（slug+release/asset slug/title）, tags, platforms（channel+platform+architecture+package_type）。
- 投影仅含已发布语义快照，读时仍 `catalog_entry_view` fail-closed 实时校验 availability，权限过滤不依赖 FTS 删除。

### 搜索 API
- `GET /api/catalog/search`：支持 q、content_type(type)、tag、platform 筛选与别名匹配（slug/release.slug/asset.slug）；返回含 `match_type` 与无结果 `suggestion`。
- 旧 `/api/search` 契约零改动。

## 尚存风险
1. **outbox 消费为读时同步**：首版未起后台消费者循环，搜索请求首次会承担消费开销。数据量大时可能增加首查询延迟。后续可加后台周期消费或 lifespan 触发。
2. **release/asset/location 的 admin CRUD 路由后端未实现**：前端 `catalog-client.ts` 有调用但后端无对应路由，故 enqueue 仅覆盖已实现的后端写操作（entry create/update/publish、location attach、tag CRUD）。若后续补全 release/asset 路由，需在对应服务层补 enqueue。
3. **FTS 召回上限 500**：`catalog_search_fts_match` limit=500，超大规模目录可能漏召回。首版目录规模可控，后续可加分页召回或 MMR。
4. **重建端点无鉴权细化**：`/api/admin/catalog/search/rebuild` 依赖现有 admin 中间件边界，未额外校验权限粒度。
5. **跨库无事务**：outbox 消费分两步 commit（index 先，state 后），若 index commit 后 state commit 前崩溃，会重复消费（水位保护使其幂等，无数据损坏，仅多一次空转）。
