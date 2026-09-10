# work02 D2 任务型专题与内容关系 — 交付结果

## 修改文件列表

### 后端 (apps/api)
- `cloudsite/models.py` — Collection 扩展 4 个专题字段；CollectionItem 加强类型字段与约束。
- `cloudsite/migrations.py` — `CURRENT_SCHEMA_VERSION` 11→13，新增 `state_v11_to_v12_upgrade`（条目强类型）与 `state_v12_to_v13_upgrade`（专题字段），注册到 STATE_MIGRATIONS。
- `cloudsite/schemas.py` — `CollectionInput` 加 goal/audience/prerequisites/item_intro；新增 `CollectionItemInput`；`CollectionItemsInput` 加强类型 `items` 并保留 `resource_ids` 兼容。
- `cloudsite/services/collections.py` — `collection_dict` 序列化新字段与双类型条目（resource + catalog_entry），item_count 统计可见条目。
- `cloudsite/services/collection_seeds.py` — 新建：幂等注入 3 个默认专题种子。
- `cloudsite/routers/admin/collections.py` — admin detail 返回强类型 items；set_items 支持强类型 `items` 与旧 `resource_ids`。
- `cloudsite/config.py` — 新增 `seed_default_collections` 开关（默认 True）。
- `cloudsite/infrastructure/lifespan.py` — 启动时按开关幂等调用种子注入。
- `tests/conftest.py` — 测试环境关闭种子注入，隔离副作用。
- `tests/test_catalog_c3_metadata_migration.py` / `tests/test_catalog_release_asset_schema.py` — 版本锚点断言 11→13。

### 前端 (apps/web)
- `src/lib/api.ts` — Collection 类型加新字段；新增 CollectionResourceItem/CollectionEntryItem/CollectionItem 联合。
- `src/app/collections/[id]/page.tsx` — 展示目标/对象/准备条件/条目说明；resource 与 catalog_entry 双类型条目渲染。
- `src/app/admin/collections/page.tsx` — 编辑器补新字段；条目管理支持资源与 Catalog 教程条目（含 note、排序、失效态）。
- `src/app/s/[token]/page.tsx` — 分享页对 collection 分享仅渲染 resource 条目（类型适配）。

## 核心改动

1. **Collection 扩展字段（state.db，迁移 state_v12_to_v13_upgrade，版本升 13）**：goal/audience/prerequisites/item_intro，复用现有 Collection 表/封面/排序，旧合集向后兼容（默认空串）。
2. **条目引用强类型**：CollectionItem 用 `item_type`('resource'|'catalog_entry') + 对应 `resource_id`/`catalog_entry_id`，不再塞同一无类型字段；保留 resource_id 列与 (collection_id,resource_id) 唯一约束，新增 (collection_id,catalog_entry_id) 唯一索引与 item_type CHECK。v11→v12 迁移幂等加列。
3. **3 个真实专题种子**：工具配置入门(8)、技能学习路径(12)、项目素材准备(10)，每个 5-15 条目，通过 catalog_entry 引用 published CatalogEntry，支持软件/教程/视频。lifespan 幂等注入，system_settings 标记去重。
4. **前端专题页**展示目标/准备条件/条目说明与双类型条目；admin 编辑页补新字段与 Catalog 条目选择器。
5. 第一版不含考试/证书/课程支付/学习管理。

## 尚存风险

- 种子注入依赖 lifespan 启动；若生产已存在同名合集不会重复（按 system_settings 标记幂等），但种子 CatalogEntry slug 固定（d2-seed-NNN），若已占用会冲突——首次部署无此问题。
- SQLite 无法对已存在表追加 CHECK 约束，item_type 取值约束仅在新建表（create_all）生效；已有库的 item_type 由 migration 默认 'resource' + 应用层校验保证。
- catalog_entry 条目在公共合集仅展示 status='published' 的 entry；种子已置 published。
- 分享页对 collection 分享仅展示 resource 条目，catalog_entry 条目不进入文件分享（符合文件分享语义）。
