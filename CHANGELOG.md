# Changelog

本项目按里程碑（M0.1 → M10）开发，版本 `0.1.0` 为 CloudSite V0.1 首个完整版本。

## [0.2.0] - 2026-08-31

### 账号与下载保护

- 新增前台用户注册、登录、退出、账户信息和修改密码，密码使用 Argon2id，服务端 Session 仅保存随机 Token Hash。
- 新增后台用户查询、禁用和恢复；禁用或修改密码会立即撤销相关旧 Session，普通用户不能替代 AList 管理员身份。
- 新增真实客户端 IP 下载限流：滑动 60 秒窗口内最多 3 次，第 4 次触发固定 60 秒等待，并返回 `429` 与 `Retry-After`。
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
