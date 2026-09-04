# CloudSite 管理员指南

> 面向管理员的配置和运维说明。普通用户请参考 [User Guide](user-guide.md)。

## 首次配置

1. 访问站点，进入后台（`/api/admin/auth/login`）
2. **系统设置** → 配置 AList 地址、账号、密码
3. **内容根** → 添加要索引的 AList 目录（如 `/软件`、`/图片`）
4. **同步** → 触发首次同步，等待索引完成

## AList 连接

- 配置 AList 服务地址和独立账号
- 凭据加密保存在 state.db
- 账号应遵循最小权限，不要使用 AList 管理员账号
- 可在"下载诊断"测试连接是否正常

## 内容根（ContentRoot）

- 每个 ContentRoot 映射一个 AList 目录到一种内容类型
- 可启用/禁用：禁用后该根的资源不出现在任何公开接口
- 删除 ContentRoot 不会删除已索引数据，但资源不再公开

## 同步（Sync）

- **首次同步**：完整扫描所有目录
- **Rolling Sync**：首次同步成功后自动迁移，24h Cycle、4 个 6h Window
- 请求默认 5～15 秒随机间隔，不超过约 2 RPS
- 缺失对象需跨两个独立 Cycle 确认才标记为 missing
- 可在后台查看 Cycle、Window、剩余目录和下次计划

## 用户管理

- 创建、改名、停用/恢复、重置密码、软删除用户
- 停用/重置密码/删除会立即撤销该用户所有 Session
- 已删除用户名永久保留
- 密码使用 Argon2id 哈希，管理界面不显示密码或哈希

## 合集（Collections）

- 跨目录、跨类型编排资源
- 可设置封面、状态、首页展示
- 合集数量只统计当前 active 资源

## 分享管理

- 查看所有分享、创建、更新、删除
- 旧版无分享码哈希的分享标记为待升级
- 可重置分享码、取消、恢复

## 站点设置

- 站点名称、首页标题、描述
- 分享页背景图上传
- 投稿邮箱、GitHub 地址
- 注册开关
- 默认分享时长

## 备份与恢复

```bash
# 备份
bash scripts/backup.sh

# 恢复（需先停止服务）
docker compose down
bash scripts/restore.sh <backup.tar.gz> --force
docker compose up -d
```

备份包含：state.db（一致性 SQLite Backup）、index.db、.env、branding。

## 诊断

- 后台"下载诊断"可测试下载链路
- `/api/health` 暴露 status + version
- 日志建议：安全日志 180 天，普通日志 30～90 天
