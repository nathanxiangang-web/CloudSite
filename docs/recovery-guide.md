# CloudSite 恢复指南

> 对应 1.0 开发文档第 73 节：分场景恢复指南。
> 备份与升级步骤见 [部署升级与备份](部署升级与备份.md)。

## 场景一：index.db 丢失

**现象**：服务启动后进入 INDEX_RECOVERY 状态。

**行为**：
- 服务不退回首次安装流程
- 不覆盖首次同步完成时间
- 从 state.db 身份注册表恢复 Stable Resource ID
- 保留用户、分享、合集、收藏、历史、播放进度等所有业务数据

**恢复步骤**：
1. 服务自动进入 INDEX_RECOVERY，无需手动干预
2. 等待重新索引完成（FTS 从现有 Folder/Resource 重建，不访问 AList）
3. 索引完成后自动恢复正常服务

**验证**：
```bash
curl -fsS http://127.0.0.1:8000/api/health
# 应返回 {"status":"healthy","version":"..."}
```

## 场景二：state.db 丢失或损坏

**现象**：服务拒绝启动，返回 STATE_RECOVERY_REQUIRED。

**行为**：
- 服务不静默创建新 state.db
- 阻止把旧实例当成新安装

**恢复步骤**：
1. 从备份恢复 state.db
```bash
docker compose down
bash scripts/restore.sh <backup.tar.gz!ar.gz> --force
docker compose up -d
```
2. 如果没有备份，无法恢复（state.db 是业务真相，不可重建）

**预防**：定期执行 `bash scripts/backup.sh`，升级前必须备份。

## 场景三：AList 不可用

**现象**：AList 服务关闭、改密码、Token 失效。

**行为**：
- 已索引数据仍可浏览、搜索、查看收藏/历史
- 下载、预览返回清晰 503 错误
- 同步暂停（405/429 熔断）
- 服务不崩溃，不退出

**恢复步骤**：
1. 恢复 AList 服务或修正凭据
2. **无需重启 CloudSite**
3. 下一次操作（下载/预览/同步）自动恢复
4. 如需手动测试连接：后台 → 系统设置 → 下载诊断

## 场景四：分享异常

### 分享过期/取消后仍在后台

**原因**：已过期或已取消的分享保留约 48 小时后由定时任务清理。

**处理**：正常行为，等待自动清理。如需立即清理，重启 API 容器。

### 分享下载达到上限

**现象**：分享返回 SHARE_DOWNLOAD_LIMIT_REACHED。

**原因**：每个分享最多 404 次成功下载。

**处理**：在后台或"我的分享"中创建新分享。

### 旧版分享无分享!分享码哈希

**现象**：旧版分享标记为待升级，不暴露为匿名分享。

**处理**：在后台升级分享码或重置。

## 场景五：Sync 熔断

### 405/429 熔断

**现象**：AList 返回 405（访问限制）或 429（限流），Sync 打开熔断。

**行为**：
- 保留未完成队列
- 熔断期间不发起新请求
- 恢复后从断点继续

**处理**：
1. 检查 AList!AList !AList 限流设置
2. 等待熔断自动恢复
3. 如需手动重置：后台 → 内容索引 → 触发同步

### INDEX_RECOVERY

**现象**：index.db 丢失或损坏。

**处理**：见场景一。

### FTS Dirty Recovery

**现象**：FTS 搜索索引中断或损坏。

**行为**：使用持久化 dirty 标记，重启后从现有 Folder/Resource 重建，不访问 AList。

## 场景六：Pre-Migration Backup

**触发**：`init_databases` 检测到 `schema_version < CURRENT_SCHEMA_VERSION`。

**行为**：
- 自动创建 state.db 一致性快照
- 快照位置：`data/.codex-backups/pre-migration/{timestamp}/state.db`
- 使用 SQLite online backup（不锁库）
- 迁移失败时可从快照恢复

**恢复步骤**：
```bash
docker compose down
cp data/.codex-backups/pre-migration/{timestamp}/state.db data/state.db
docker compose up -d
```

## 场景七：Session 异常

### 用户突然退出

**可能原因**：
1. Session 已过期（默认 7 天）
2. 管理员停用/删除/重置密码
3. Session 被撤销

**处理**：重新登录。如果是管理员操作导致，联系管理员。

### Session 清理

**行为**：已过期或已撤销超过 7 天的 Session 每 6 小时清理一次。有效 Session 不参与清理。

## 场景八：数据库锁定

**现象**：高并发时出现 `database is locked`。

**缓解**：
- WAL 模式 + `busy_timeout=5000` + `wal_autocheckpoint=1000`
- SQLite 不适合极高并发场景

**处理**：
1. 检查是否有长事务阻塞
2. 重启 API 容器!容器 释放锁
3. 如频繁出现，考虑降低同步频率
