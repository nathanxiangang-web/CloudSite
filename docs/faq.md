# CloudSite FAQ

## 为什么视频不能播放？

CloudSite 使用浏览器原生解码，不转码、不代理文件主体。支持 MP4 H.264/AAC。如果浏览器不支持该编码（如 HEVC/H.265、某些 MKV 容器），视频无法播放。此时请使用下载功能，用本地播放器打开。

## 为什么下载跳到了 AList？

CloudSite 通过 HTTP 302 将下载请求重定向到 AList 原生下载入口，不代理文件主体。这是设计决策，避免 CloudSite 成为文件传输瓶颈。下载速度取决于 AList 和存储后端。

## 为什么某些资源搜不到？

可能原因：
1. 资源所属的内容根已被禁用
2. 资源状态为 missing（连续两个同步周期未发现）
3. 搜索索引尚未更新（FTS 在 Window 结束后重建）
4. 资源路径被 `.cloudsite` 忽略规则排除

## 为什么账号突然退出了？

可能原因：
1. Session 已过期（默认 7 天）
2. 管理员停用了你的账号
3. 管理员重置了你的密码
4. 管理员删除了你的账号
5. Session 被撤销（密码修改等操作触发）

## 为什么分享过期了还在后台？

已过期或已取消的分享会保留约 48 小时后由定时任务清理。在此期间分享仍出现在后台列表，但无法被访问。

## index.db 能不能删？

可以。index.db 是可重建索引。删除后服务进入 INDEX_RECOVERY 状态，从 state.db 身份注册表恢复，不会退回首次安装或覆盖首次同步历史。但建议先备份。

## state.db 能不能删？

**不能。** state.db 是业务真相数据库，包含用户、Session、AList 配置、分享、合集、Stable Resource ID 等。删除会丢失所有业务数据。如果 state.db 损坏，请从备份恢复。

## 为什么下载有次数限制？

同一 IP 滑动 60 秒内最多 5 次下载，第 6 次需等待 60 秒。这是下载频率限制，防止滥用。分享下载也有每分享最多 404 次的限制。

## Rolling Sync 和首次同步有什么区别？

首次同步完整扫描所有目录建立索引。首次同步成功后自动迁移到 Rolling Sync：24h Cycle、4 个 6h Window，每个 Window 校验一部分目录。迁移不请求 AList、不重建现有索引。

## Generic AList 支持增量同步吗？

不支持。Generic AList 使用 Rolling Full Verification，不宣传伪 Delta。只有明确声明 Delta 能力的 Provider 才进入 Delta Strategy。
