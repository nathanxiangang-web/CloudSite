# CloudSite 1.0 公开契约

> 本文档是 CloudSite 1.0 稳定契约的单一事实来源。
> 1.0 发布后，以下契约进入冻结状态：可以新增，不能随意重命名或删除。
> 若需废弃，先在 1.x 标记 deprecated，2.0 才删除。

---

## 1. 公开 URL 路由

### 1.1 匿名公开（无需认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查，返回 status + version |
| POST | `/api/auth/login` | 前台用户登录 |
| POST | `/api/auth/register` | 前台用户注册（受站点开关控制） |
| GET | `/api/site` | 公开站点配置 |
| GET | `/api/public/share-page` | 分享页配置 |
| GET | `/api/public/share-page/image` | 分享页背景图 |
| GET | `/api/public/shares/{token}` | 分享详情 |
| POST | `/api/public/shares/{token}/verify` | 验证分享码 |
| GET | `/api/public/shares/{token}/content` | 分享内容 |
| GET | `/api/public/shares/{token}/download` | 分享下载（资源） |
| GET | `/api/public/shares/{token}/download/{resource_id}` | 分享下载（文件夹/合集中指定资源） |
| GET | `/s/{token}` | 分享入口页 |
| GET | `/s/{token}/d` | 分享直下（资源） |
| GET | `/s/{token}/d/{resource_id}` | 分享直下（指定资源） |

### 1.2 前台用户（需要 User Session）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/home` | 首页数据 |
| GET | `/api/storage/info` | 存储信息 |
| GET | `/api/content-roots` | 内容根列表 |
| GET | `/api/resources` | 资源列表（分页、过滤、排序） |
| GET | `/api/resources/{resource_id}` | 资源详情 |
| GET | `/api/resources/{resource_id}/preview` | 预览网关（302） |
| GET | `/api/resources/{resource_id}/text-preview` | 文本预览 |
| GET | `/api/resources/{resource_id}/office-preview` | Office 预览 |
| GET | `/api/resources/{resource_id}/pdf-preview` | PDF 预览 |
| GET | `/office-files/{filename}` | Office 预览文件 |
| GET | `/api/folders` | 文件夹列表 |
| GET | `/api/folders/{folder_id}` | 文件夹详情 |
| GET | `/api/search` | 搜索 |
| GET | `/api/collections` | 合集列表 |
| GET | `/api/collections/{collection_id}` | 合集详情 |
| GET | `/api/shares/{token}` | 分享信息（查看） |
| GET | `/d/{resource_id}` | 下载网关（302） |
| GET | `/p/{resource_id}` | 预览网关（302） |
| POST | `/api/auth/logout` | 退出登录 |
| GET | `/api/auth/me` | 当前用户信息 |
| POST | `/api/auth/change-password` | 修改密码 |
| POST | `/api/favorites/{resource_id}` | 添加收藏 |
| DELETE | `/api/favorites/{resource_id}` | 移除收藏 |
| GET | `/api/favorites/{resource_id}` | 检查收藏状态 |
| GET | `/api/favorites` | 收藏列表 |
| POST | `/api/history/{resource_id}/touch` | 记录浏览历史 |
| GET | `/api/history` | 历史列表 |
| DELETE | `/api/history/{resource_id}` | 删除单条历史 |
| DELETE | `/api/history` | 清空历史 |
| GET | `/api/playback/{resource_id}` | 播放进度 |
| PUT | `/api/playback/{resource_id}` | 保存播放进度 |
| DELETE | `/api/playback/{resource_id}` | 删除播放进度 |
| GET | `/api/playback` | 播放进度列表 |
| GET | `/api/my/shares` | 我的分享列表 |
| POST | `/api/my/shares` | 创建分享 |
| PATCH | `/api/my/shares/{token}` | 更新分享 |
| DELETE | `/api/my/shares/{token}` | 删除分享 |

### 1.3 管理后台（需要 Admin Session）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/auth/status` | 管理员认证状态 |
| POST | `/api/admin/auth/login` | 管理员登录 |
| POST | `/api/admin/auth/logout` | 管理员退出 |
| GET | `/api/admin/overview` | 仪表盘概览 |
| GET | `/api/admin/users` | 用户列表 |
| GET | `/api/admin/users/{user_id}` | 用户详情 |
| POST | `/api/admin/users` | 创建用户 |
| PATCH | `/api/admin/users/{user_id}` | 更新用户 |
| PATCH | `/api/admin/users/{user_id}/status` | 启用/停用用户 |
| POST | `/api/admin/users/{user_id}/reset-password` | 重置密码 |
| DELETE | `/api/admin/users/{user_id}` | 删除用户 |
| POST | `/api/admin/downloads/diagnose` | 下载诊断 |
| GET | `/api/admin/downloads/diagnostics` | 诊断记录 |
| GET | `/api/admin/identities/stats` | 身份统计 |
| GET | `/api/admin/identities/candidates` | 身份候选 |
| GET | `/api/admin/alist` | AList 连接配置 |
| POST | `/api/admin/alist/test` | 测试 AList 连接 |
| PUT | `/api/admin/alist` | 更新 AList 连接 |
| GET | `/api/admin/alist/directories` | AList 目录浏览 |
| GET | `/api/admin/root-mappings` | 内容根列表 |
| POST | `/api/admin/root-mappings` | 创建内容根 |
| PUT | `/api/admin/root-mappings/{mapping_id}` | 更新内容根 |
| DELETE | `/api/admin/root-mappings/{mapping_id}` | 删除内容根 |
| POST | `/api/admin/sync` | 触发同步 |
| GET | `/api/admin/sync/status` | 同步状态 |
| POST | `/api/admin/sync/auto-toggle` | 自动同步开关 |
| POST | `/api/admin/sync/window/run` | 执行 Rolling Window |
| POST | `/api/admin/search/rebuild` | 重建搜索索引 |
| GET | `/api/admin/index/summary` | 索引摘要 |
| GET | `/api/admin/index/folders` | 文件夹列表 |
| GET | `/api/admin/index/folders/{folder_id}` | 文件夹详情 |
| GET | `/api/admin/sync-runs` | 同步运行记录 |
| GET | `/api/admin/sync-runs/{run_id}/changes` | 同步变更详情 |
| GET | `/api/admin/collections` | 合集列表 |
| GET | `/api/admin/collections/{collection_id}` | 合集详情 |
| POST | `/api/admin/collections` | 创建合集 |
| PUT | `/api/admin/collections/{collection_id}` | 更新合集 |
| PUT | `/api/admin/collections/{collection_id}/items` | 更新合集资源 |
| DELETE | `/api/admin/collections/{collection_id}` | 删除合集 |
| GET | `/api/admin/shares` | 分享列表 |
| POST | `/api/admin/shares` | 创建分享 |
| PATCH | `/api/admin/shares/{token}` | 更新分享 |
| DELETE | `/api/admin/shares/{token}` | 删除分享 |
| GET | `/api/admin/system` | 系统设置 |
| PUT | `/api/admin/system` | 更新系统设置 |
| GET | `/api/admin/site` | 站点设置 |
| PUT | `/api/admin/site` | 更新站点设置 |
| POST | `/api/admin/site/share-image` | 上传分享页图片 |
| DELETE | `/api/admin/site/share-image` | 删除分享页图片 |

---

## 2. API Error Code

所有错误响应统一格式：

```json
{
  "detail": {
    "code": "ERROR_CODE",
    "message": "可读消息"
  }
}
```

### 2.1 Auth / Session

| Code | HTTP | 说明 |
|------|------|------|
| `AUTH_REQUIRED` | 401 | 需要登录 |
| `SESSION_INVALID` | 401 | Session 无效 |
| `SESSION_REVOKED` | 401 | Session 已撤销 |
| `SESSION_EXPIRED` | 401 | Session 已过期 |
| `USER_DELETED` | 401 | 用户已删除 |
| `USER_DISABLED` | 403 | 用户已停用 |
| `ADMIN_REQUIRED` | 403 | 需要管理员权限 |

### 2.2 Share

| Code | HTTP | 说明 |
|------|------|------|
| `SHARE_NOT_FOUND` | 404 | 分享不存在 |
| `SHARE_TARGET_INVALID` | 404 | 分享目标不存在或不可用 |
| `SHARE_RESOURCE_NOT_ALLOWED` | 403 | 资源不属于当前分享 |
| `SHARE_RESOURCE_REQUIRED` | 400 | 需要指定资源 |
| `SHARE_TICKET_INVALID` | 403 | 分享票据无效 |
| `SHARE_CODE_INVALID` | 400 | 分享码错误 |
| `SHARE_CODE_REQUIRED` | 400 | 需要分享码 |
| `SHARE_CODE_NOT_REQUIRED` | 400 | 此分享不需要分享码 |
| `SHARE_DIRECT_HAS_NO_CODE` | 400 | 直下分享无分享码 |
| `SHARE_DIRECT_RESOURCE_ONLY` | 400 | 直下分享仅限单资源 |
| `SHARE_DOWNLOAD_LIMIT_REACHED` | 403 | 达到下载上限 |
| `SHARE_DURATION_INVALID` | 400 | 有效期无效 |
| `SHARE_DURATION_REQUIRED` | 400 | 需要指定有效期 |
| `SHARE_CAPTCHA_REQUIRED` | 429 | 需要验证码 |
| `SHARE_ACTION_NOT_ALLOWED` | 403 | 操作不允许 |
| `USER_SHARE_RESOURCE_ONLY` | 400 | 用户分享仅限资源 |

### 2.3 Share Image

| Code | HTTP | 说明 |
|------|------|------|
| `SHARE_IMAGE_EMPTY` | 400 | 图片为空 |
| `SHARE_IMAGE_INVALID` | 400 | 图片格式无效 |
| `SHARE_IMAGE_NOT_FOUND` | 404 | 图片不存在 |
| `SHARE_IMAGE_TOO_LARGE` | 413 | 图片过大 |

### 2.4 Download / Resource / Preview / Search / Folder

| Code | HTTP | 说明 |
|------|------|------|
| `DOWNLOAD_RATE_LIMITED` | 429 | 下载频率受限 |
| `RESOURCE_NOT_AVAILABLE` | 404 | 资源不可用 |
| `RS-001` | 400 | 资源参数无效 |
| `PV-001` | 400 | 预览参数无效 |
| `PV-002` | 404 | 预览不可用 |
| `FD-001` | 400 | 文件夹参数无效 |
| `SRCH-001` | 400 | 搜索参数无效 |
| `SRCH-002` | 400 | 搜索词无效 |
| `SRCH-003` | 400 | 搜索类型无效 |
| `SRCH-004` | 400 | 搜索排序无效 |
| `API-001` | 400 | 通用参数无效 |

### 2.5 AList

| Code | HTTP | 说明 |
|------|------|------|
| `AL-006` | 400 | AList 参数错误 |
| `AL-999` | 502 | AList 操作失败 |

### 2.6 System

| Code | HTTP | 说明 |
|------|------|------|
| `VALIDATION_ERROR` | 422 | 请求参数格式不正确 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |
| `HTTP_{status}` | * | 未明确映射的 HTTP 错误 |

---

## 3. 环境变量

### 3.1 冻结变量（1.0 后不可重命名）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLOUDSITE_SECRET_KEY` | （必填） | 会话签名 + 凭据加密回退 |
| `CLOUDSITE_MASTER_KEY` | （空） | 独立主密钥，优先用于凭据加密 |
| `CLOUDSITE_DATA_DIR` | `data` | 容器内数据目录 |
| `CLOUDSITE_DATA_PATH` | `./data` | 宿主机数据目录（Compose） |
| `CLOUDSITE_CORS_ORIGINS` | `http://localhost:3000` | CORS 来源（逗号分隔，禁止 `*`） |
| `CLOUDSITE_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128,172.16.0.0/12` | 可信代理网段 |
| `CLOUDSITE_SYNC_MISSING_CONFIRM_RUNS` | `2` | 缺失确认所需独立扫描次数 |
| `CLOUDSITE_OFFICE_CACHE_TTL_SECONDS` | `3600` | Office 预览缓存 TTL |
| `CLOUDSITE_OFFICE_CACHE_MAX_BYTES` | `209715200` | Office 预览缓存上限 |

### 3.2 部署变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLOUDSITE_WEB_BIND` | `0.0.0.0` | Web 监听地址 |
| `CLOUDSITE_WEB_PORT` | `3000` | Web 监听端口 |
| `CLOUDSITE_API_IMAGE` | `ghcr.io/.../cloudsite-api` | API 镜像 |
| `CLOUDSITE_WEB_IMAGE` | `ghcr.io/.../cloudsite-web` | Web 镜像 |
| `CLOUDSITE_IMAGE_TAG` | `v0.5.1` | 镜像版本标签 |
| `CLOUDSITE_DOMAIN` | `cloud.example.com` | Traefik 域名 |
| `TRAEFIK_NETWORK` | `my-servers_app-net` | Traefik 网络 |
| `TRAEFIK_ENTRYPOINT` | `websecure` | Traefik 入口点 |
| `TRAEFIK_CERT_RESOLVER` | `myresolver` | Traefik 证书解析器 |
| `API_INTERNAL_URL` | `http://api:8000` | 前端访问 API 内部地址 |
| `NEXT_PUBLIC_SITE_NAME` | `CloudSite` | 站点名称 |

---

## 4. Docker Volume

| 宿主机 | 容器内 | 内容 |
|--------|--------|------|
| `${CLOUDSITE_DATA_PATH:-./data}` | `/data` | state.db、index.db、office-cache、branding |

**禁止**执行 `docker compose down -v`，未备份时不要删除 `data/`。

---

## 5. 数据库所有权

### 5.1 state.db — 业务真相（必须备份）

| 表 | 说明 |
|----|------|
| `alist_connections` | AList 连接配置（加密凭据） |
| `site_settings` | 站点设置 |
| `system_settings` | 系统设置 + schema_version |
| `content_root_mappings` | 内容根映射 |
| `download_events` | 下载事件 |
| `download_diagnostics` | 下载诊断 |
| `operation_logs` | 操作日志 |
| `collections` | 合集 |
| `collection_items` | 合集资源项 |
| `shares` | 分享 |
| `share_verify_attempts` | 分享验证尝试 |
| `users` | 用户 |
| `user_sessions` | 用户 Session |
| `user_favorites` | 收藏 |
| `user_resource_history` | 浏览历史 |
| `user_playback_progress` | 播放进度 |
| `download_rate_limits` | 下载限流记录 |
| `resource_identities` | Stable Resource ID 注册表 |
| `resource_identity_history` | 身份历史 |
| `resource_identity_candidates` | 身份候选 |

### 5.2 index.db — 可重建索引（建议备份）

| 表 | 说明 |
|----|------|
| `folders` | 文件夹索引 |
| `resources` | 资源索引 |
| `sync_runs` | 同步运行记录 |
| `sync_root_results` | 同步根结果 |
| `sync_changes` | 同步变更 |
| `sync_cycles` | Rolling Cycle |
| `sync_cycle_items` | Cycle Item |
| `folder_scan_state` | 文件夹扫描状态 |
| `provider_sync_state` | Provider 同步状态 |
| `search_fts` | FTS5 全文搜索虚拟表 |
| `_schema_meta` | Schema 版本元数据 |

**语义**：删除 index.db → INDEX_RECOVERY（不是首次安装）；删除 state.db → 拒绝启动。

---

## 6. 传输契约

| 入口 | 行为 |
|------|------|
| `/d/{resource_id}` | CloudSite 校验 → AList Entry → **302** |
| `/p/{resource_id}` | CloudSite 校验 → AList Entry → **302** |
| `/s/{token}/d...` | Share 校验 → Stable ID → AList Entry → **302** |

**1.0 禁止改为 Body Proxy。** CloudSite 不代理文件主体。

---

## 7. 认证契约

- 站内默认要求 User Session
- Public Zone 只有明确白名单（见 1.1）
- Admin Auth 与 Public User Auth 分离
- Disabled / Deleted / Reset Password 触发 Session 熔断
- Cookie: `cloudsite_session`（Admin）、`cloudsite_user_session`（User）均为 HttpOnly

---

## 8. 分享契约

- `/s/{token}` 匿名入口
- 4 位分享码（HMAC 哈希存储）
- 固定有效期枚举：5m / 1h / 6h / 24h / 7d / permanent
- Expired / Cancelled 约 48h 清理
- 每分享最多 404 次成功下载
- CloudSite 302 to AList（不代理主体）
