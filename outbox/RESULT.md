# work03 C4 资源关注、版本更新与通知 - 交付结果

## 修改文件列表

### 后端（apps/api）
- `cloudsite/models.py`：新增 `CatalogFavorite`、`CatalogSubscription`、`CatalogReleaseNotification` 三张 StateBase 表。
- `cloudsite/migrations.py`：`CURRENT_SCHEMA_VERSION` 升至 10；新增 `state_v9_to_v10_upgrade` 幂等迁移并注册到 `STATE_MIGRATIONS`。
- `cloudsite/services/catalog_follow.py`（新增）：C4 应用层——关注/取关/状态查询/退订/我的关注列表/发布通知触发与去重。
- `cloudsite/services/catalog.py`：`update_catalog_release` 在 release 从非 published 变为 published 时调用 `notify_release_subscribers`。
- `cloudsite/routers/catalog_follow.py`（新增）：`/api/me/catalog/favorites*` 路由，登录用户私有。
- `cloudsite/main.py`：注册 `catalog_follow_router`。
- `tests/test_catalog_follow_service.py`（新增）：C4 最小自测 9 例。

### 前端（apps/web）
- `src/app/account/page.tsx`：账号页新增"我的关注"入口，"我的收藏"改为"文件收藏"，二者并列。
- `src/app/account/follows/page.tsx`（新增）：我的关注列表页，含条目最新发布版本摘要、退订开关、取关、与文件收藏互链。
- `src/app/catalog/[entryId]/page.tsx`：详情页 header 加关注/取关按钮。
- `src/components/catalog/CatalogFollowButton.tsx`（新增）：关注按钮组件，未登录引导登录。
- `src/lib/catalog-client.ts`：追加关注 API 客户端函数与类型。

## 核心改动

1. **数据模型**：`CatalogFavorite(user_id, entry_id)` 唯一约束——条目级关注，与 `UserFavorite`（文件级收藏）严格分离，文件收藏/历史/播放进度语义零改动。`CatalogSubscription(user_id, entry_id, notify_enabled)` 唯一约束——通知订阅开关，可独立退订而保留关注。`CatalogReleaseNotification(release_id, user_id)` 唯一约束——通知去重幂等记录。
2. **迁移**：`state_v9_to_v10_upgrade` 幂等创建三张表与索引，FK 在 state.db 内声明，ondelete=CASCADE 随用户/条目/版本删除清理。空库、重复执行、v9 旧库升级均通过（沿用现有 migration 测试模式）。
3. **关注 API**：`POST/DELETE/GET/PATCH /api/me/catalog/favorites/{entry_id}` + `GET /api/me/catalog/favorites`。关注时同步创建订阅（notify_enabled=True）；仅允许关注已发布条目，避免泄漏未发布；列表分页且仅返回仍为 published 的条目，含最新已发布 release 摘要。
4. **更新通知**：`update_catalog_release` 在 status→published 时触发 `notify_release_subscribers`，向 notify_enabled=True 的订阅者推送 `Notification(source="catalog_release")`，按 `(release_id, user_id)` 唯一约束去重，重复发布不重复通知；普通字段更新（非 publish）不触发；退订用户不收到；在请求事务内完成，不引入新基础设施。
5. **前端**：账号页"我的关注"与"文件收藏"并列、类型明确、可互链；详情页关注按钮未登录引导登录，已登录显示关注/取关与通知开关。

## 尚存风险

- 通知去重依赖 `CatalogReleaseNotification` 的 `(release_id, user_id)` 唯一约束与发布前 SELECT 检查；并发同 release 发布理论上由唯一约束兜底（savepoint 隔离），但单进程后台场景下不会触发并发。
- `notify_release_subscribers` 在 `update_catalog_release` 事务内同步执行，关注者量大时事务耗时增长；首版未做批量/异步，符合"不引入新基础设施、请求流程内完成"约束，但超大规模关注者需后续优化。
- 我的关注列表对每个条目单独查询 release 列表以取最新摘要，N+1 查询；首版关注量预期不大，后续可优化为聚合查询。
- 前端"我的关注"页与详情页关注按钮共享 query key 失效，但未与通知铃铛联动刷新（通知列表仍需手动刷新）。
- 首版分享部分（资产选择后创建文件分享）按任务书要求不做。
