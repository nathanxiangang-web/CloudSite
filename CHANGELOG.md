# Changelog

本项目按里程碑（M0.1 → M10）开发，版本 `0.1.0` 为 CloudSite V0.1 首个完整版本。

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
