# work01 C2 交付闭环 + B1 呈现 端到端测试结果

## 新增测试列表

### 后端（apps/api/tests/）
1. **test_catalog_download_route.py**（7 个）— C2 下载签发端点
   - `test_download_entry_not_published_returns_404`：entry 未发布 → 404
   - `test_download_release_not_published_returns_404`：release 未发布 → 404
   - `test_download_asset_disabled_returns_409_with_reason`：asset 禁用 → 409 带 reason=asset_disabled
   - `test_download_no_available_location_returns_409`：无有效 location → 409 带 reason=no_enabled_location
   - `test_download_success_returns_302_to_allowed_location`：正常 → 302 且 Location 指向服务端解析的允许位置
   - `test_download_audit_records_file_id`：审计记录实际 file_id（download_events source='catalog', result='success'）
   - `test_download_ignores_client_mirror_url`：POST body 携带 mirror_url/url/upstream_url 被忽略，Location 仍为服务端 URL

2. **test_catalog_admin_crud_route.py**（5 个）— C2 release/asset/location CRUD
   - `test_release_crud`：release 创建/编辑/删除
   - `test_asset_crud`：asset 创建/编辑/删除
   - `test_location_crud`：location 创建/编辑/删除
   - `test_delete_release_with_assets_returns_409`：删除含 asset 的 release → 409 CATALOG_DELETE_CONFLICT
   - `test_recommended_release_uniqueness`：推荐版本唯一（任意时刻最多一个推荐 release）

3. **test_presentation_route.py**（5 个）— B1 presentation 路由
   - `test_presentation_get_default`：初始默认状态
   - `test_presentation_save_and_rollback`：保存配置后回退到历史快照
   - `test_presentation_schema_rejects_invalid_home_blocks`：schema 拒绝非法 home_blocks type/preset/theme_tokens
   - `test_presentation_apply_preset`：software/tutorial 预设切换
   - `test_presentation_toggle`：启用/停用切换

### 前端（apps/web/tests/）
4. **catalog-delivery.test.mts**（8 个）— 选包页
   - 推荐版本排序优先、历史版本排后
   - 无推荐时历史排后
   - 仅展示已发布版本
   - 平台/架构维度标签 fallback
   - 平台/架构筛选（含空值归一化）
   - 不可用资产展示"暂不可用"且无可下载位置
   - 可用资产优先选 primary location
   - entry 可用性守卫

## 通过数
- 后端三个文件：17 passed
- 后端全量回归：493 passed
- 前端全量：44 passed

## 发现的行为差异（非阻塞，未自行修复）

### 1. 推荐版本唯一：实现采用"顶替"而非"拒绝"
- **任务书期望**：推荐版本唯一（第二个推荐被拒，返回 409）
- **实际实现**：`services/catalog.py` 的 `create_catalog_release` / `update_catalog_release` 在 `is_recommended=True` 时调用 `_clear_other_recommendations`，先清除同 entry 下其他 release 的推荐标记，再设置当前 release 为推荐，返回 201/200 而非 409。
- **影响**：最终仍保证"任意时刻最多一个推荐 release"（唯一性不变量成立），数据库 partial unique index `ux_catalog_releases_one_recommended_per_entry` 也不会被触发。
- **测试处理**：`test_recommended_release_uniqueness` 验证唯一性不变量（通过）。未断言"第二个返回 409"，因实现行为为顶替。
- **复现**：对同一 entry 连续 POST 两个 `is_recommended=true` 的 release，第二个返回 201，第一个的 is_recommended 变为 false。

### 2. apply-preset 的 PRESET_UNKNOWN (400) 分支不可达
- **观察**：`routers/admin/presentation.py` 的 `ApplyPresetInput.preset` 为 `Literal["software", "tutorial"]`，pydantic 在路由前即拒绝非 software/tutorial 的值（422 VALIDATION_ERROR），路由内 `PRESET_UNKNOWN` (400) 分支为防御性死代码。
- **测试处理**：`test_presentation_apply_preset` 断言未知预设返回 422（schema 层拒绝）。
- **影响**：无功能影响，仅防御性分支不可达。
