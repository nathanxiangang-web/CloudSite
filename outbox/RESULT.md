# work01 C2 多版本与平台交付闭环 — 交付结果

## 修改文件列表

### 后端（apps/api）
- `cloudsite/models.py`：`CatalogAsset` 新增 `language`、`build_label` 列。
- `cloudsite/migrations.py`：新增 `state_v7_to_v8_upgrade`（幂等加列+索引），`CURRENT_SCHEMA_VERSION` 升至 8，注册到 `STATE_MIGRATIONS`。
- `cloudsite/services/catalog.py`：
  - `create_catalog_release` 扩展 `channel`/`release_date`/`is_recommended`，新增 `_clear_other_recommendations` 维护"每条目至多一个推荐"不变量。
  - `create_catalog_asset` 扩展 `architecture`/`package_type`/`language`/`build_label`/`checksum`/`checksum_algorithm`/`size`。
  - 新增 `update_catalog_release`/`update_catalog_asset`/`update_catalog_location`/`delete_catalog_location`、`get_catalog_release`/`get_catalog_asset`、`list_catalog_releases`/`list_catalog_assets`/`list_catalog_locations`。
  - 新增 `resolve_asset_download_target` 与 `CatalogAssetNotDownloadable`：校验 entry 已发布→release 已发布→asset 启用→至少一个启用且有效的 location，优先主位置，返回 `AssetDownloadTarget(resource_id, location_id)`。绝不接受客户端镜像 URL。
- `cloudsite/catalog_schemas.py`：新增 release/asset/location 的 Create/Update Input（`extra="forbid"`，稳定 ID pattern，unknown/universal 显式默认）。
- `cloudsite/routers/admin/catalog.py`：补全契约 4.1 的 release/asset/location CRUD 路由（GET/POST/PATCH/DELETE），复用 `catalog_release_view`/`catalog_asset_view`，删除 release 时拒绝仍含 asset 的版本（`CATALOG_DELETE_CONFLICT`）。
- `cloudsite/routers/catalog.py`：新增 `POST /api/catalog/entries/{entry_id}/assets/{asset_id}/download` 签发端点，复用 1.0.0 `resolve_download_entry`+限流+`_download_event` 审计（`source="catalog"`），未发布/不存在返回 404，禁用/无有效位置返回 409 并带 `reason`。
- `cloudsite/services/catalog_views.py`：`catalog_asset_view` 补 `language`/`build_label`，`catalog_release_view` 补 `release_date`。
- `tests/test_catalog_release_asset_schema.py`：版本断言升至 v8，新增 `language`/`build_label` 列与默认值断言。

### 前端（apps/web）
- `src/lib/catalog.ts`：`CatalogAssetSummary` 加 `architecture`/`package_type`/`language`/`build_label`；`CatalogReleaseSummary` 加 `channel`/`is_recommended`/`release_date`；新增渠道标签与推荐/历史判断 helpers。
- `src/lib/catalog-client.ts`：`CatalogReleaseInput`/`CatalogAssetInput` 扩展字段；新增 `catalogAssetDownloadPath`。
- `src/app/admin/catalog/entries/[entryId]/page.tsx`：ReleaseManager 创建表单加 渠道/发布日期/推荐版本，行内可切换推荐（显式 `is_recommended`，不靠字符串比较）；AssetManager 创建表单加 架构/包型/语言/构建标签，行内展示架构与包型。
- `src/app/catalog/[entryId]/page.tsx`：选包页增强——版本按推荐优先、历史靠后排序，展示渠道标签与推荐标记；交付物按平台/架构/包型筛选；每张资产卡片明确"可下载/暂不可用"并展示平台/架构/包型/语言/大小；下载改为 `POST` 到签发 API（表单提交，浏览器跟随 302），不再直接拼 `/d/{resource_id}`。

## 核心改动

1. **推荐版本语义**：`is_recommended` 显式布尔 + 部分唯一索引 `ux_catalog_releases_one_recommended_per_entry`，应用层 `_clear_other_recommendations` 在设新推荐前清除同条目旧推荐，绝不按 `slug`/`title` 字符串排序取"最新"。
2. **下载签发 API**：服务端校验 entry/release/asset 发布与启用状态、解析到允许且有效的 location（主位置优先），复用 1.0.0 的 302 解析与限流，审计记录实际 `resource_id`；不可用返回明确错误码（`CATALOG_ASSET_NOT_FOUND` 404 / `CATALOG_ASSET_NOT_DOWNLOADABLE` 409 带 `reason`：`asset_disabled`/`no_enabled_location`/`no_available_location` 等）。
3. **unknown/universal 明确区分**：`architecture`/`package_type`/`language` 默认 `unknown`，`platform` 默认空串（UI 显示"通用"），不自动猜测 Windows/x64。
4. **release/asset/location CRUD**：补全契约 4.1 全部路由，前端原有 client 调用不再 404。
5. **兼容性**：未改动 `/d/{id}`、`/resource/{id}`、分享/收藏/历史；catalog 仍是 overlay，不移动底层文件；state/index 分库保持，location 可用性由服务层批量检查。

## 尚存风险

- 下载签发端点用表单 POST 触发浏览器跟随 302；若 AList 返回 inline 而非 `Content-Disposition: attachment`，浏览器可能导航而非下载。生产可改为隐藏 iframe 或服务端强制 attachment，首版未做。
- `update_catalog_release`/`update_catalog_asset` 未引入乐观并发 token（契约将子对象乐观锁推迟到实测并发需求），多人同时编辑同一 release/asset 可能后写覆盖先写。
- 删除 release 时仅检查"是否仍有 asset"，未检查 asset 是否有已发布 location；契约要求"无 active location 的 asset"才可删 release，当前实现更保守（要求无任何 asset），符合安全方向但略严。
- 前端管理端 release/asset 的"编辑已有记录"仅暴露状态切换与推荐切换，完整字段编辑（如改 title/channel/architecture）依赖 `updateAdminCatalogRelease`/`updateAdminCatalogAsset` 已就绪但未在 UI 全量铺开，首版以创建+状态+推荐为主。
- 未新增针对 download 签发端点与 release/asset CRUD 路由的独立测试用例（TASK.md 约定完整测试由架构师统一补）；现有 `test_catalog_routes.py` 的路由注册断言未覆盖新增路径。
