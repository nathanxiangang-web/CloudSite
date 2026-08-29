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
- 同步任务后台执行，浏览器立即收到“已启动”，长时间扫描不会被反向代理误报失败。
- AList 列表请求默认限制为 2 RPS 并加入随机间隔；支持 3/6/12/24 小时自动同步、手动冷却和访问限制熔断。
- 仅在内容根完整扫描成功后提交该根的缺失差异；扫描失败保留旧索引，并对异常大规模变化进行保护。

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

### 2. 生产环境启动

```bash
docker compose up -d
```

默认的 `docker-compose.yml` 使用 GHCR 预构建镜像并接入 Traefik。首次启动前请确认外部网络 `my-servers_app-net` 已存在，并在 `.env` 设置域名和密钥。

首次打开后台后，在“系统设置”中配置 AList 地址和管理账号，再设置内容根目录映射并执行同步。

### 本地源码构建

本地开发或测试时使用独立文件：

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

前台默认为 `http://localhost:3000`，API 为 `http://localhost:8000`。

### 可选：本地使用 Caddy

设置 `.env` 中的 `CLOUDSITE_DOMAIN` 后执行：

```bash
docker compose -f docker-compose.dev.yml -f docker-compose.caddy.yml up -d --build
```

### 使用现有 Traefik 发布到公网

默认的 `docker-compose.yml` 就是完整生产配置，用于接入已存在的 Traefik 网络。它不会直接映射 3000 或 8000 端口，而是由 Traefik 将 HTTPS 域名转发到前端服务。

默认从 GitHub Container Registry 拉取已构建镜像，公网服务器无需安装 Node.js、Python 构建环境，也无需现场构建：

```bash
# 拉取 .env 中 CLOUDSITE_IMAGE_TAG 指定的版本
docker compose pull

# 使用预构建镜像启动或升级
docker compose up -d
```

Compose 默认固定为 `v0.1.2`；升级时可在 `.env` 设置新的 `CLOUDSITE_IMAGE_TAG`。需要跟随主分支最新镜像时可改为 `latest`，但生产环境不建议长期使用浮动标签。

每次向 `main` 推送或创建 `v*` Git 标签时，GitHub Actions 会分别构建并发布：

- `ghcr.io/nathanxiangang-web/cloudsite-api`
- `ghcr.io/nathanxiangang-web/cloudsite-web`

两个 Container package 设为 Public 后，服务器可匿名拉取；若保持 Private，需先用具备 `read:packages` 权限的令牌执行 `docker login ghcr.io`。

默认配置使用外部网络 `my-servers_app-net` 和证书解析器 `myresolver`；如果你的 Traefik 名称不同，请先调整 `docker-compose.yml`。

## 常用操作

```bash
# 查看服务状态
docker compose ps

# 查看实时日志
docker compose logs -f

# 停止服务（不会删除 data 目录）
docker compose down

# 本地重新构建并启动
docker compose -f docker-compose.dev.yml up -d --build

# 生产环境升级到 .env 指定的 GHCR 版本
docker compose pull
docker compose up -d
```

运行数据位于 `./data`，其中包含站点配置和可重建的内容索引。升级或迁移前请先备份该目录；`scripts/backup.sh` 与 `scripts/restore.sh` 可辅助执行备份和恢复。

## 开发与验证

需要 Docker、Docker Compose、Python 3.12+，前端依赖使用 pnpm 10。

```bash
# 后端测试
docker compose -f docker-compose.dev.yml run --rm api pytest

# 前端类型检查
docker compose -f docker-compose.dev.yml run --rm web npm run lint

# 构建镜像
docker compose -f docker-compose.dev.yml build
```

## 同步安全模型

- 周期和普通手动同步使用 AList 已有目录状态，不强制逐目录刷新 Storage。
- 一个同步任务按内容根顺序执行；同一时间只允许一个任务运行。
- 内容根扫描成功后，索引以本次真实结果更新，未出现项目可直接标记为缺失。
- 内容根扫描失败时保留该根旧数据，不把“没扫到”当成“已删除”。
- 检测到 405、访问限制或异常大规模路径变化时，暂停提交并等待冷却，避免持续请求或误删索引。

## 安全说明

- `.env`、`data/`、备份、预览缓存和运行日志均已被 `.gitignore` 排除。
- AList 管理账号仅用于服务端连接和后台身份验证；请使用独立账号并最小化权限。
- 下载链接由 AList 临时生成，可能会过期；访问失败时在后台“下载诊断”中重新测试。

## 许可证

本项目采用仓库中的 [LICENSE](LICENSE) 许可。
