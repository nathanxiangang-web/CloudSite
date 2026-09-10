# work01 B1 场景预设与首页区块 — 交付结果

## 修改文件列表（17 个）

### 后端（Python）
- `apps/api/cloudsite/models.py`：新增 `SitePresentation`（单例，当前生效配置）与 `SitePresentationRevision`（历史快照）两个 StateBase 模型。
- `apps/api/cloudsite/migrations.py`：`CURRENT_SCHEMA_VERSION` 11→12；新增幂等迁移 `state_v11_to_v12_upgrade`（建 site_presentation / site_presentation_revisions 表 + 索引）并注册到 STATE_MIGRATIONS。
- `apps/api/cloudsite/services/presentation.py`（新）：两套预设常量（SOFTWARE_PRESET / TUTORIAL_PRESET）、pydantic schema（PresentationConfig / HomeBlock / NavigationItem / ThemeTokens）、受支持区块类型 featured/recent/topic/category/continue、验证与序列化辅助。
- `apps/api/cloudsite/routers/admin/presentation.py`（新）：后台 API——GET 配置/预设/历史、PUT 发布配置、POST apply-preset、POST rollback、PUT toggle。每次发布写历史快照，回退生成新 revision 不覆盖历史。
- `apps/api/cloudsite/routers/home.py`：`/api/home` 增加 `presentation`（enabled/preset/theme_tokens/navigation/ordered_blocks）与 `topics`（已发布 catalog 条目）字段。
- `apps/api/cloudsite/site.py`：`/api/site` 增加 `presentation` 字段，供前台动态导航与主题。
- `apps/api/cloudsite/main.py`：注册 admin_presentation_router。
- `apps/api/tests/test_catalog_release_asset_schema.py`、`test_catalog_c3_metadata_migration.py`：版本断言 11→12。

### 前端（TSX）
- `apps/web/src/app/admin/presentation/page.tsx`（新）：后台配置页——启停、预设切换、导航编辑、区块排序（上移/下移/启停/limit/title）、主题色、预览顺序、发布、历史回退。
- `apps/web/src/components/HomeContent.tsx`：按 `presentation.ordered_blocks` 顺序渲染区块；未启用或停用时回退到原默认顺序（旧默认主题可恢复）；每区块无资源时有可理解空状态。
- `apps/web/src/components/FeaturedTopics.tsx`（新）：推荐专题区块，渲染已发布 catalog 条目。
- `apps/web/src/components/ContinueSection.tsx`（新）：继续使用区块，客户端获取 `/api/me/history`，未登录时空状态。
- `apps/web/src/components/FeaturedCollections.tsx`：接受可选 `limit` / `title` 参数。
- `apps/web/src/components/PublicShell.tsx`：顶部导航按 `presentation.navigation` 动态渲染，未启用时回退原 TOPBAR_NAV。
- `apps/web/src/components/AdminShell.tsx`：新增"站点呈现"菜单项（/admin/presentation）。
- `apps/web/src/lib/site.tsx`：PublicSiteSettings 类型增加 `presentation` 字段与对应类型。

## 核心改动

1. **SitePresentation 模型（state.db，schema v12）**：单例 id=1，字段 preset（software/tutorial/custom，CHECK 约束）、theme_tokens_json、navigation_json、home_blocks_json、config_revision、enabled。配置以受控 JSON 文本存储，经 pydantic schema 验证后写入，不直接执行用户代码。
2. **两套预设**：软件站（category→featured→recent→topic→continue，蓝色）、教程站（topic→featured→category→recent→continue，绿色）。预设为 Python 常量，通过 API apply-preset 切换，无需改源码。共用现有资源/合集/catalog 能力，不引入独立数据库或业务分支。
3. **历史与回退**：SitePresentationRevision 表保存每次发布快照；回退生成新 revision 而非覆盖历史，旧默认主题（enabled=False）仍可恢复。
4. **首页区块渲染**：HomeContent 按 ordered_blocks 顺序渲染受支持类型区块；无资源时每区块显示可理解空状态，不是空壳布局。
5. **动态导航**：PublicShell 顶部导航按 presentation.navigation 渲染。

## 尚存风险

- continue 区块依赖用户登录态（`/api/me/history`），未登录时显示空状态提示；该区块数据未纳入 `/api/home` 缓存以避免跨用户泄漏，由客户端独立获取。
- 首版未开发自由拖拽页面编辑器（符合任务书要求）；区块排序通过上移/下移按钮实现。
- theme_tokens 目前仅 accent_color 与 card_radius，主题变量注入到 CSS 未做全量落地（首版聚焦区块与导航），后续 X3 主题包契约再扩展。
- 推荐专题区块取已发布 catalog 条目按 sort_order/published_at 排序，未支持预设内"推荐专题 ID 白名单"显式绑定（首版按排序取数即可用）。
