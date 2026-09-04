# CloudSite 架构

> 对应 1.0 开发文档第 69 节：正式画出 Browser → CloudSite → AList → Storage，并写清下载/预览 = 302。

## 系统架构

```
                     Browser
                        ↓
                 Next.js / React
                        ↓
                     FastAPI
       ┌────────────────┼─────────────────┐
       ↓                ↓                 ↓
    Auth/User        Business          Sync
       ↓                ↓                 ↓
   state.db        state.db/index.db  Provider
       │                │                 ↓
       │                │               AList
       │                │                 ↓
       └──────────────┬─┴────────────── Storage
                      ↓
              Stable Resource ID
                      ↓
       Browse / Search / Collection
       Favorite / History / Playback
       Preview / Download / Share
                      ↓
                  HTTP 302
```

## 传输语义

下载、二进制预览、分享下载均使用 HTTP 302 跳转到 AList 原生入口，CloudSite 不代理文件主体。

| 入口 | 流程 |
|------|------|
| `/d/{resource_id}` | CloudSite 校验 → AList Entry → **302** |
| `/p/{resource_id}` | CloudSite 校验 → AList Entry → **302** |
| `/s/{token}/d...` | Share 校验 → Stable ID → AList Entry → **302** |

**设计决策**：避免 CloudSite 成为文件传输瓶颈，下载速度取决于 AList 和存储后端。1.0 禁止改为 Body Proxy。

## 数据库所有权

### state.db — 业务真相（必须备份）

| 类别 | 表 |
|------|-----|
| 连接配置 | `alist_connections`、`site_settings`、`system_settings`、`content_root_mappings` |
| 用户体系 | `users`、`user_sessions`、`user_favorites`、`user_resource_history`、`user_playback_progress` |
| 分享 | `shares`、`share_verify_attempts` |
| 合集 | `collections`、`collection_items` |
| 身份 | `resource_identities`、`resource_identity_history`、`resource_identity_candidates` |
| 运维 | `download_events`、`download_diagnostics`、`operation_logs`、`download_rate_limits` |

**语义**：删除 state.db → 拒绝启动（STATE_RECOVERY_REQUIRED），不静默创建新库。

### index.db — 可重建索引（建议备份）

| 类别 | 表 |
|------|-----|
| 索引 | `folders`、`resources`、`search_fts`（FTS5 虚拟表） |
| 同步 | `sync_runs`、`sync_root_results`、`sync_changes`、`sync_cycles`、`sync_cycle_items`、`folder_scan_state`、`provider_sync_state` |

**语义**：删除 index.db → INDEX_RECOVERY（从 state.db 身份恢复，不退回首次安装）。

## Sync 架构

### 首次同步

完整扫描所有 ContentRoot 目录，建立 Folder/Resource 索引和 FTS 搜索索引。

### Rolling Full Verification

首次同步成功后自动迁移到 Rolling：

```
24h Cycle = 4 个 6h Window
每个 Window 校验一部分目录
请求默认 5～15 秒随机间隔，不超过约 2 RPS
```

| 机制 | 说明 |
|------|------|
| 缺失确认 | 跨两个独立 Cycle 未见才标记 missing |
| Scope 保护 | 大规模路径变化触发零写入保护 |
| 重启恢复 | 持久化 Cycle/Window/Folder 进度，重启后继续 |
| 405/429 熔断 | AList 限流时打开熔断，保留未完成队列 |

### Provider Capability

Generic AList 默认声明 Delta 能力为 NO，使用 Rolling Full Verification。只有明确声明 Delta 能力的 Provider 才进入 Delta Strategy。1.0 不宣传 Generic AList "真正增量"。

## 认证架构

```
Admin Auth（cloudsite_session）
  → AList 管理员凭据 → 后台配置
  → 独立于前台用户体系

User Auth（cloudsite_user_session）
  → 前台用户注册/登录
  → Session Token Hash 存储
  → Disabled/Deleted/Reset Password → Session 熔断
```

**公开白名单**：`/api/health`、`/api/auth/login`、`/api/auth/register`、`/api/site`、`/api/public/shares/*`、`/s/*`。其余所有端点要求 User Session。

## 分享架构

```
/s/{token} → 匿名入口（无需 CloudSite 账号）
  → 4 位分享码（HMAC 哈希存储，不存明文）
  → 验证成功 → 签发短时 HttpOnly 票据（仅限当前分享路径）
  → CloudSite 302 to AList
```

| 属性 | 值 |
|------|-----|
| 分享码 | 4 位，HMAC 哈希存储 |
| 有效期 | 5m / 1h / 6h / 24h / 7d / permanent |
| 下载上限 | 每分享 404 次 |
| 清理 | Expired/Cancelled 约 48h 后清理 |

## Stable Resource ID

```
新资源 → 128-bit 随机 ID
已有资源 → 原样保留（0.3.0 迁移不换 ID）

身份解析（保守策略）：
  同路径 → 复用 ID
  可靠 Rename/Move → 保留 ID
  Copy / Path Reuse → 生成新 ID
  歧义场景 → 宁可新 ID，不误合并
```

**边界**：Generic AList 无法 100% 识别所有 Move/Copy。Folder ID 仍可能 Path-derived。

## 视频架构

```
Browser Native Decode
  → CloudSite 不转码、不代理文件主体、不预生成 HLS
  → 支持 MP4 H.264/AAC
  → 不承诺所有 MKV/AVI/HEVC
  → Decode Failure → 下载降级
```

1.0 不把 FFmpeg、HLS、GPU 加入必需依赖。
