# Changelog

本项目按里程碑（M0.1 → M10）开发，版本 `0.1.0` 为 CloudSite V0.1 首个完整版本。

## [1.0.0-beta.3] - 2026-09-05

### Added

- 首页 Hero 插画组件 `HeroIllustration.tsx` 与响应式动画，桌面/移动端自适应。
- 前端 ESLint 配置 `eslint.config.mjs`，建立 lint、typecheck、test、build 四道门禁。
- CI 工作流接入四道前端门禁与版本一致性脚本。

### Changed

- React 19 / Next.js 兼容整改：admin、login、search、submit、resource 等页面与 AdminShell、AuthMenu、GalleryCard、DownloadButton、HomeContent 等组件适配 React 19 类型与渲染契约。
- UI 设计令牌与控件尺寸统一；主题切换按钮、通知铃铛在桌面与移动端尺寸一致。
- 默认与 Traefik Compose、`.env.example`、README、`docs/contracts.md` 发布标签更新为 `v1.0.0-beta.3`。

### Fixed

- `globals.css` 行尾空白与 CRLF 规范化为 LF，保留 Hero 动画数值。
- 后端 `main.py` 重复导入清理。
- 文档与版本一致性修复（API `pyproject.toml`、`__init__.py`、Web `package.json`、Compose 默认 tag、README 离线资产名）。

## [1.0.0-beta.2] - 2026-09-05

### Added

- Admin auth module `admin_auth.py` with setup/notifications/submissions admin pages; added admin route policy, route inventory and route matrix tests.
- Publication scope hardening test `test_publication_scope.py` and submissions notifications test `test_submissions_notifications.py`.

### Changed

- Public endpoints filter disabled ContentRoot; Office preview isolates disabled roots.
- Web static assets migrated from PNG to WebP.

### Fixed

- CI: pnpm lockfile consistency, Compose env, pip-audit local package skip, cryptography>=50 and pytest>=9 upgrade.
- Docker build switched to webpack; arm64 images built on native arm64 runner to avoid QEMU SIGILL.

## [1.0.0-beta.1] - 2026-09-04

### 1.0 稳定发布候选

CloudSite 1.0 不再堆大功能；冻结架构、冻结公开契约、完成升级/恢复/兼容/安全/文档/发布闭环。

### Added

- 新增公开契约文档 `docs/contracts.md`：URL 路由表、Error Code 表、Env 变量表、Docker Volume、DB ownership 单一事实来源。
- 新增用户指南 `docs/user-guide.md`、管理员指南 `docs/admin-guide.md`、FAQ `docs/faq.md`、限制说明 `docs/limitations.md`。
- 新增 Pre-Migration Backup：`init_databases` 检测到旧 `schema_version` 时自动创建 state.db 一致性快照到 `.codex-backups/pre-migration/`。
- 新增错误契约回归测试 `test_error_contract.py`：验证所有错误响应格式一致、不泄漏 traceback/internal path/secret。
- 新增 Public DTO 审计测试 `test_dto_audit.py`：验证序列化函数不泄漏 password_hash/code_hash/raw_url/sign 等敏感字段。
- 新增旧版本迁移 fixture 测试 `test_migration_fixtures.py`：验证 init_databases 数据保留、幂等性、view_count 同步。
- 新增 Pre-Migration Backup 测试 `test_pre_migration_backup.py`：验证新库/旧库/最新库的快照行为。
- 新增 Publication Scope 泄漏测试 `test_publication_scope.py`：验证 disabled ContentRoot 资源不出现在任何公开接口。
- 新增 IDOR 测试 `test_idor.py`：验证 favorites/history/playback/shares 用户隔离。
- 新增 Secret Leak 测试 `test_secret_leak.py`：验证 health/me/admin/错误响应不泄漏密钥。
- 新增 Scheduler 隔离测试 `test_scheduler_isolation.py`：验证 cleanup 异常不传播、scheduler_loop 存活 sync 失败。
- 新增 AList Offline 测试 `test_alist_failure.py`：验证 AList 不可用时浏览/搜索仍工作、下载返回清晰错误。
- 新增 Graceful Shutdown 测试 `test_graceful_shutdown.py`：验证 lifespan 取消 scheduler_task 和 manual_sync_task。

### Changed

- README 新增文档索引表，链接所有用户/管理员/契约/FAQ/限制文档。

### Fixed

- **Publication Scope 泄漏修复**：`/api/home`、`/api/resources`、`/api/resources/{id}`、`/d/{id}`、`/p/{id}` 五个端点现在正确过滤 disabled ContentRoot 的资源，不再泄漏已禁用根的数据。

### Security

- Publication Scope 是公开数据的最终边界（1.0 文档第 32 节）：所有 Browse/Search/Resource Detail/Download/Preview 都不让非 enabled ContentRoot 数据重新公开。
- Public DTO 审计确保 password_hash、session_token_hash、password_ciphertext、raw_url、sign、code_hash 不出现在公开 API 响应中。

### Migration Notes

- 从 0.5.1 升级到 1.0.0-beta.1 无破坏性 schema 变更（CURRENT_SCHEMA_VERSION 保持为 1）。
- init_databases 会在检测到旧 schema_version 时自动创建迁移前快照，无需手动干预。
- 升级前仍建议执行 `bash scripts/backup.sh` 创建完整备份。

## [0.5.1] - 2026-09-04

### 整改与收敛

- 视频详情回归单层浏览器原生 controls，移除重复的播放、静音、全屏、画中画和倍速工具栏；保留错误重试、下载、媒体信息与继续播放提示。
- 新增收藏、浏览历史和播放进度数据表/API及账号页面；全部引用 Stable Resource ID，并按启用的发布根过滤不可用资源。
- 播放进度改为 Last Write Wins，播放中最多每 15 秒写一次；暂停、完播、页面隐藏时补写，5 秒以内不创建记录。
- 注册开关同时约束前端入口和后端注册接口；基础站点文案、投稿邮箱、GitHub 地址和默认分享时长通过单次公开配置下发。
- Branding Logo/Favicon 上传与聚合 Dashboard 延期；Generic AList 保持 Rolling，同步 Delta 代码只作为不影响主链路的 dormant 能力。
- `/p/{resource_id}` 保持 HTTP 302，不代理视频主体，并增加 preview/provider/redirect 调试计时。

## [0.4.1] - 2026-09-03

### Provider Capability 抽象

- 新增 `providers/` 抽象层：`ProviderCapabilities` 三态能力（yes/no/unknown）、`StorageProvider` 接口、`GenericAListProvider`、`ProviderRegistry` 与 `SyncStrategyResolver`。
- Generic AList 默认声明 delta 相关能力为 NO、Range 为 UNKNOWN，因此同步策略保持 Rolling 全量校验；未知 Provider 一律回退 generic_alist，绝不自动启用 Delta。
- 新增 Delta 契约：`ProviderChange`、`SyncStrategy`、`DeltaSyncStrategy`（Cursor 事务模型：只有本批安全 Commit 后才推进 cursor，失败重放，cursor 失效回退 Full Bootstrap）、`FakeDeltaProvider`。
- 新增 `provider_sync_state` 表（index.db）与 AListConnection 的 `provider_type` / `provider_capabilities_json` 等字段（state.db），启动迁移自动补齐。
- 后台「系统」新增 Provider 能力卡片：Provider / 同步策略 / Delta / Change Cursor / Webhook / Stable Object ID / Range / Direct Preview 及回退原因。

## [0.4.0] - 2026-09-03

### 浏览器原生视频体验

- 新增 `VideoPlayer` 组件（`components/video/`）：倍速、画中画、全屏、静音、键盘快捷键（Space/K、←→±5s、M、F）、时长/分辨率展示、重新加载与下载降级。
- 视频继续走浏览器原生解码，CloudSite 不转码、不代理文件主体、不预生成 HLS。
- MediaError 按 network/decode/source_not_supported 分类给出可读提示，失败时保留下载入口与兼容性说明。
- 倍速/音量/静音偏好持久化到 localStorage；列表页不预加载媒体，仅详情页创建播放器。
- 后端 Preview DTO 增强：新增 `browser_native`、`mime_type`、`extension` 字段。

## [0.3.4] - 2026-09-03

### 分享页 UI 优化

- 分享页由「左侧面板 + 右侧独立图片」升级为「整页背景 + 独立前景面板」：背景图使用 `position:fixed` + `background-size:cover` 铺满整个 viewport，不再参与左右分栏缩放，浏览器缩放或不同分辨率下保持整体感。
- 左侧提取面板宽度使用 `clamp(380px, 24vw, 460px)`，在超宽屏不再随比例无限变宽；背景只裁切、不拉伸。
- 背景仅通过 `@media (min-width:1100px)` 应用 `background-image`，手机端不下载大图；小屏直接隐藏背景、面板占满全宽并居中内容。
- 长文件名使用 `overflow-wrap` 保护，不撑宽面板；面板允许内容过高时轻微滚动，Footer 使用 `margin-top:auto` 不遮挡表单。
- 后台「分享页图片」说明更新为整页背景口径，推荐比例 3:2、尺寸 1800×1200 或以上，预览改为 3:2 比例。

## [0.3.3] - 2026-09-02

### 分享下载网关

- 分享新增 4 位分享码与单文件无分享码直下两种模式；分享码只保存 HMAC 哈希，验证成功后签发短时、仅限当前分享路径的 HttpOnly 票据。
- `/s/{token}` 成为匿名分享入口，分享码和无分享码模式都不要求 CloudSite 账号登录；普通站点页面、预览与原下载接口继续要求登录，无分享码模式仅允许单个有效资源。
- 分享支持 5 分钟、1 小时、6 小时、24 小时、7 天和永久有效期，并记录查看、下载、最近下载与取消原因。
- 每个分享最多成功下载 404 次，计数使用数据库原子更新；达到上限后自动取消，避免并发请求绕过限制。
- 旧版无分享码哈希的分享标记为待升级，不会直接暴露为匿名分享；后台支持升级、重置分享码、取消、恢复和删除。
- 分享验证页采用桌面左右分栏与移动端单栏布局，右侧展示图可在“网站设置”上传、替换或移除；未配置时保持留空。
- 普通登录用户可从资源详情页创建单文件分享，并在“我的分享”中查看、复制、改期、重置分享码、取消或删除自己的分享。
- 下载频率限制调整为同一真实客户端 IP 在滑动 60 秒内最多成功发起 5 次，第 6 次触发固定 60 秒等待。

### 运维与清理

- 启动时自动补齐 0.3.3 分享字段与验证尝试表，保留已有分享和统计数据。
- 定时清理取消或过期超过 48 小时的分享，以及过期验证尝试记录。

## [0.3.2] - 2026-09-01

### 多架构发布

- GHCR API/Web 镜像新增 `linux/arm64`，与现有 `linux/amd64` 共同发布为多架构 Manifest。
- GitHub Release 同时生成 AMD64 与 ARM64 离线镜像，并在安装文档中补充架构选择方法。

## [0.3.1] - 2026-09-01

### 响应式 UI

- 新增独立移动端 Header、账号入口与五项图文导航，桌面 Sidebar 不再缩成移动端图标条。
- 重排移动端 Hero、搜索、网盘状态、分类、精选合集、最近更新和热门资源布局。
- 桌面 AppShell、Sidebar、Main 与 Footer 使用 `100dvh` 和 Flex 等高逻辑；平板使用紧凑侧栏。
- 修复移动端横向溢出、最近更新字段隐藏不完整，并优化首页首张合集图片加载优先级。

## [0.3.0] - 2026-09-01

### Stable Resource ID

- 现有 Resource ID 原样种入 `state.db` 身份注册表，不进行破坏性的批量换 ID；新资源改用 128-bit 随机 ID。
- 完整扫描与 Rolling Scan 统一使用保守身份解析：同路径直接复用，可靠的 Rename / Move 保留 ID，Copy 与 Path Reuse 生成新 ID，歧义场景不自动合并。
- 跨目录 Rolling Move / Copy 先进入 Pending，等源目录在同一 Cycle 完成扫描后再决定复用旧 ID 或生成新 ID。
- 新增身份历史、候选队列、后台统计和迁移前自动 SQLite 快照；`index.db` 重建时可从 `state.db` 恢复同路径身份。

### 用户邮箱投稿与搜索布局

- 新增登录后 `/submit` 投稿页，固定发送至 `nathxo@outlook.com`；只生成本地 `mailto:` 模板，不新增上传、SMTP、Submission DB 或 AList 写权限。
- 投稿页支持复制邮箱、复制正文、无邮件客户端降级、HTTP(S) 链接校验、隐私与版权提示。
- About 与 Footer 增加投稿入口；搜索页补齐长搜索词、超长无空格文件名和窄屏的收缩与断行边界。

## [0.2.2] - 2026-09-01

### 长期运行与安全收口

- 新增 Session 与下载限流定时清理，保留有效会话并限制高频 `last_seen_at` 写入。
- 新增 `state.db` / `index.db` 启动前只读健康检查，阻止旧实例在 `state.db` 丢失后被误判为首次安装。
- FTS 重建加入持久化 dirty 标记，重启后可直接从现有索引恢复，不依赖 AList 在线。
- Rolling Window 在 405 与 429 时统一打开熔断，并保留未完成队列供恢复后继续。
- 仅信任已配置反向代理网段的 `X-Forwarded-*`，统一 HTTPS Cookie、来源校验和真实客户端地址边界；带凭据 CORS 禁止通配符。
- 后端错误响应统一为带稳定 `code` 与可理解 `message` 的 JSON，前端鉴权熔断统一清缓存并返回登录页。
- 新增安全、迁移、数据库恢复、AList 断线恢复和 Rolling 重启回归测试。

## [0.2.1] - 2026-08-31

### 发布与安装

- GitHub Release 提供 API、Web 两个 `linux/amd64` 离线 Docker 镜像包、离线部署模板和 SHA256 校验文件。
- 新增离线安装说明与 `docker-compose.offline.yml`；离线启动固定使用版本标签并禁止连接 GHCR 拉取镜像。

### 强制登录与用户生命周期

- 前台注册、登录及后台用户创建/改名统一使用 2～16 位用户名，允许字母、数字、下划线和短横线。
- 首页、浏览、搜索、合集、分享、预览与下载统一要求有效前台用户 Session；仅健康检查、登录和注册 API 匿名开放。
- 后端逐请求核验 Session、过期时间及用户实时状态，分别拒绝伪造、撤销、过期、停用和软删除账号，不能仅靠页面地址绕过。
- 后台用户管理补齐创建、详情、改名、停用/恢复、重置密码和软删除；停用、重置密码、删除均原子撤销该用户全部 Session。
- 已删除用户名永久保留，密码只保存 Argon2id 哈希，管理界面不显示、接口不返回密码或哈希。
- 前端新增服务端页面保护、全局鉴权失效跳转及安全 `next` 返回地址校验。

## [0.2.0] - 2026-08-31

### 账号与下载保护

- 新增前台用户注册、登录、退出、账户信息和修改密码，密码使用 Argon2id，服务端 Session 仅保存随机 Token Hash。
- 新增后台用户查询、禁用和恢复；禁用或修改密码会立即撤销相关旧 Session，普通用户不能替代 AList 管理员身份。
- 新增真实客户端 IP 下载限流；当前规则为滑动 60 秒窗口内最多 5 次，第 6 次触发固定 60 秒等待，并返回 `429` 与 `Retry-After`。
- 限流状态使用匿名 IP HMAC 写入 `state.db`，支持刷新、浏览器重开和 API 重启后保持；并发请求使用 SQLite 原子事务防止绕过。
- 下载按钮新增服务端剩余时间提示，倒计时仅负责显示，不作为权威状态。

## [0.1.4] - 2026-08-30

### Sync Engine 1.1

- 已完成首次索引的 v0.1.x 实例可一次性迁移到 Rolling Full Verification；迁移保留现有 Folder、Resource、合集、配置和首次同步历史，不重新执行首次同步。
- 24 小时 Cycle 固定拆为 4 个 6 小时窗口，每个窗口按 `remaining / remaining_windows` 动态分配 Folder，不设置固定请求次数上限。
- 新增自适应 Request Governor：默认保持 5～15 秒随机间隔，大规模目录按 2 小时窗口目标适度提速，绝对不超过约 2 RPS。
- 新增持久化 `sync_cycles`、`sync_cycle_items`、`folder_scan_state`，服务重启后恢复原 Cycle，已完成目录不重复扫描。
- Rolling Scope 使用严格响应校验、直接 children Fingerprint、Scope-aware Diff、跨不同 Cycle 的两次 Missing 确认和 Scope 零写入保护。
- 无业务变化的 Window 跳过 FTS；有变化时只在 Window 结束后重建一次。
- `index.db` 丢失时根据 `state.db` 身份进入 INDEX_RECOVERY，不重新进入首次安装流程，也不重写首次同步完成时间。
- 后台内容索引页新增 Rolling Cycle、Window、剩余目录、请求量和下次计划展示。

## [0.1.3] - 2026-08-30

### 开源部署收口

- 默认 `docker-compose.yml` 改为通用 GHCR 部署，不再依赖指定的 Traefik 网络，直接开放 Web 端口 3000。
- 新增独立 `docker-compose.traefik.yml` 和可配置的网络、入口点、证书解析器参数。
- 新增完整 CI：后端测试、前端类型检查与构建、Compose 校验、Docker 构建冒烟；全部通过后才发布镜像。
- 补齐干净安装、升级、回滚、备份和恢复说明。
- 补齐首页“查看全部”对应的公开合集列表页，消除 `/collections` 404。
- 合集数量只统计当前 active 资源，避免失效引用造成列表数量与详情内容不一致。

### 同步安全

- 对象首次未扫描到时标记为 `suspected_missing`，仅在第二次独立完整扫描仍缺失时标记为 `missing`。
- 大规模路径变化改为内容根级零写入保护；候选新增和候选缺失只记入审计，不再出现“保留旧项同时写入全部新项”的索引膨胀。
- 修正 README 下载链路口径：CloudSite 构造 AList Native `/d/` 入口并返回 HTTP 302，不解析最终 Storage `raw_url`，不代理文件主体。

## [0.1.2] - 2026-08-29

### 同步可靠性

- 手动同步改为后台任务，接口立即返回 `202 Accepted`，避免长扫描触发 Next.js/Traefik 超时误报。
- AList 目录列表默认限速为 2 RPS，并加入随机间隔、手动冷却、失败退避及 405/访问限制熔断。
- 自动同步间隔收敛为 3/6/12/24 小时；启动同步只在上次成功同步已到期时执行。
- 每个内容根独立提交；扫描失败保留旧索引，完整成功后才应用缺失差异。
- 异常大规模路径变化触发保护，不直接提交 missing 状态。

### 发布

- 修复 Next.js standalone 容器在多 Docker 网络下绑定错误网卡导致的 Traefik 502。
- 新增 GitHub Actions，自动发布 API 与 Web 的 `linux/amd64` GHCR 镜像。
- 生产 Compose 支持版本化 GHCR 拉取，公网服务器可直接升级，无需现场构建。

## [0.1.0] - 2026-08-28

### 核心能力

- **M1 AList 连接**：加密保存 AList 凭据、连接测试、后台会话（HttpOnly）。
- **M2 动态索引**：任意深度目录扫描，双 SQLite（`state.db` 配置 / `index.db` 可重建索引），内容根映射，同步历史。
- **M3 浏览**：首页、资源库、文件夹详情、资源详情、真实数据接入。
- **M4 搜索**：FTS5 全文搜索，资源/文件夹检索，类型过滤与相关度排序。
- **M5 下载**：`/d/{resource_id}` 302 到 AList 原生 `/d/` 入口，CloudSite 零文件主体代理、不按文件大小分支。
- **M6 预览**：`/p/{resource_id}` 预览网关，图片 / 视频 / PDF / 文本 / Markdown，失败降级。
- **M7 精选合集**：跨目录、跨类型资源编排，首页展示，后台管理（资源选择器、状态、封面）。
- **M8 分享**：文件 / 文件夹 / 合集分享，有效期、状态、访问统计、后台管理。
- **M9 后台收口**：后台 7 页面真实联调，Mock 清理，权限与错误处理统一。
- **M10 部署**：Docker Compose + Caddy，数据持久化，备份 / 恢复 / 升级流程。

### 技术栈

FastAPI（SQLAlchemy async + SQLite）· Next.js 16（React 19）· Docker Compose · Caddy。

### 原则

- CloudSite 负责资源校验、能力判定与 302 跳转；AList 负责 Storage Driver 与最终直链。
- 下载/二进制预览不代理文件主体，不按 `Resource.size` 选择策略。
- 不引入 Redis / Celery / FFmpeg / Office 转换。
