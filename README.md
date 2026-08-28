# CloudSite

CloudSite 将 AList 中的网盘目录转换为可浏览、搜索、预览和分享的资源网站，并支持从浏览器经由应用返回 AList 的 302 直连下载。

> 这是从已完成的部署实例整理出的干净发布源码包：不包含 AList 账号、访问令牌、`.env`、数据库索引、运行日志、开发过程文档、设计素材、依赖目录或构建产物。

## 功能概览

- 使用 AList 凭据连接网盘，配置在服务端加密保存。
- 扫描任意深度目录，按软件、图片、视频、文档等资源分类并支持搜索。
- 支持图片、视频、PDF 和常见 Office 文档预览。
- 支持合集、资源分享链接、有效期与访问统计。
- 资源下载由 `/d/{resource_id}` 实时向 AList 请求 `raw_url`，应用返回 302 跳转，不将网盘直链写入索引。
- 内置后台概览、内容索引、合集、分享、下载诊断、站点设置、同步历史和 AList 后台认证。

## 技术栈

- 前端：Next.js 16、React 19、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLAlchemy、SQLite
- 部署：Docker Compose；可选 Caddy 反向代理与 HTTPS

## 快速启动

### 1. 准备环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少将 `CLOUDSITE_SECRET_KEY` 替换为高强度随机字符串。该文件仅在本机或服务器保存，切勿提交到仓库。

### 2. 启动服务

```bash
docker compose up -d --build
```

服务默认地址：

- 前台：`http://localhost:3000`
- API：`http://localhost:8000`

首次打开后台后，在“系统设置”中配置 AList 地址和管理账号，再设置内容根目录映射并执行同步。

### 可选：使用 Caddy

设置 `.env` 中的 `CLOUDSITE_DOMAIN` 后执行：

```bash
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build
```

## 常用操作

```bash
# 查看服务状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 停止服务（不会删除 data 目录）
docker compose down

# 重新构建并启动
docker compose up -d --build
```

运行数据位于 `./data`，其中包含站点配置和可重建的内容索引。升级或迁移前请先备份该目录；`scripts/backup.sh` 与 `scripts/restore.sh` 可辅助执行备份和恢复。

## 开发与验证

需要 Docker、Docker Compose、Python 3.12+，前端依赖使用 pnpm 10。

```bash
# 后端测试
docker compose run --rm api pytest

# 前端类型检查
docker compose run --rm web npm run lint

# 构建镜像
docker compose build
```

## 安全说明

- `.env`、`data/`、备份、预览缓存和运行日志均已被 `.gitignore` 排除。
- AList 管理账号仅用于服务端连接和后台身份验证；请使用独立账号并最小化权限。
- 下载链接由 AList 临时生成，可能会过期；访问失败时在后台“下载诊断”中重新测试。

## 许可证

本项目采用仓库中的 [LICENSE](LICENSE) 许可。
