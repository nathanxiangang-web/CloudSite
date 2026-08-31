# CloudSite

CloudSite 将 AList 中的网盘目录转换为可浏览、搜索、预览和分享的资源网站，并通过 AList 原生下载入口提供浏览器 302 直连下载。

> 发布源码不包含 AList 账号、访问令牌、`.env`、数据库、索引、日志、依赖目录或构建产物。

## 功能概览

- 使用 AList 凭据连接网盘，配置在服务端加密保存。
- 扫描任意深度目录，按软件、图片、视频、文档等类型浏览和搜索。
- 支持图片、视频、PDF、文本、Markdown 和常见 Office 文档预览。
- 支持精选合集、资源分享链接、有效期与访问统计。
- 支持独立的前台用户注册、强制登录、账户安全与后台用户完整生命周期管理；普通用户身份不与 AList 管理员身份混用。
- 资源下载由 `/d/{resource_id}` 解析 Resource，向 AList 获取文件信息及签名，构造 AList Native `/d/` 下载入口并返回 HTTP 302。
- 登录用户下载按真实客户端 IP 固定执行滑动 60 秒最多 3 次、第 4 次等待 60 秒；状态持久化在 `state.db`，刷新页面或重启 API 均不能绕过。
- CloudSite 不解析最终 Storage `raw_url`、不代理文件主体，也不按文件大小选择下载策略。
- 内置后台概览、内容索引、合集、分享、下载诊断、站点设置、同步历史和 AList 后台认证。
- 首次同步保持原有完整内容根扫描流程不变；Sync Engine 1.1 只在首次同步成功并已有索引后迁移接管，迁移不请求 AList、不重建现有索引。
- 后续校验按 24 小时 Cycle、4 个 6 小时 Window 覆盖全部目录；请求默认随机间隔 5～15 秒，并根据窗口工作量动态调速，绝对不超过约 2 RPS。
- Rolling Scope 严格校验 AList 响应；缺失对象需跨两个独立 Cycle 确认，大规模路径变化按目录 Scope 零写入保护。

## 技术栈

- 前端：Next.js 16、React 19、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLAlchemy、SQLite
- 部署：Docker Compose；可选 Traefik HTTPS

## 一键部署

要求：Docker Engine 与 Docker Compose Plugin。服务器无需安装 Node.js 或 Python。

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
cp .env.example .env
```

编辑 `.env`，至少替换 `CLOUDSITE_SECRET_KEY`。随后启动：

```bash
docker compose up -d
docker compose ps
```

打开 `http://服务器IP:3000`。默认 Compose 只公开 Web 端口 `3000`，API 仅在内部网络提供服务，运行数据保存在 `./data`。

除登录和注册外，前台页面、资源接口、分享、预览和下载均要求有效 CloudSite 用户登录。管理后台继续使用独立的 AList 管理员认证。

首次进入后台后，在“系统设置”中配置 AList 地址和独立账号，再配置内容根并执行同步。

## 离线安装

没有外网、不能访问 GHCR 的服务器，请从 GitHub Releases 下载当前版本的离线附件，不要执行 `docker compose pull`：

- `cloudsite-api-v0.2.1-linux-amd64.tar.gz`
- `cloudsite-web-v0.2.1-linux-amd64.tar.gz`
- `cloudsite-v0.2.1-offline-deploy.zip`
- `SHA256SUMS.txt`

在联网电脑下载并校验附件，复制到离线服务器后导入两个镜像，再使用离线 Compose 覆盖文件启动：

```bash
sha256sum -c SHA256SUMS.txt
gzip -dc cloudsite-api-v0.2.1-linux-amd64.tar.gz | docker load
gzip -dc cloudsite-web-v0.2.1-linux-amd64.tar.gz | docker load
unzip cloudsite-v0.2.1-offline-deploy.zip -d CloudSite
cd CloudSite
cp .env.example .env
# 编辑 .env，至少替换 CLOUDSITE_SECRET_KEY
docker compose -f docker-compose.yml -f docker-compose.offline.yml config --images
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d --wait
```

离线包为 `linux/amd64`，目标服务器仍需事先安装 Docker Engine 与 Docker Compose Plugin。完整传输、安装、验收和离线升级步骤见 [`docs/离线安装.md`](docs/离线安装.md)。

## 使用现有 Traefik

在 `.env` 中设置：

```dotenv
CLOUDSITE_DOMAIN=cloud.example.com
TRAEFIK_NETWORK=my-servers_app-net
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_CERT_RESOLVER=myresolver
```

确认外部网络已经存在，然后启动独立 Traefik 配置：

```bash
docker network inspect "$TRAEFIK_NETWORK"
docker compose -f docker-compose.traefik.yml up -d
```

`docker-compose.traefik.yml` 不映射宿主机端口，由现有 Traefik 通过指定网络访问 Web 容器。

## 本地源码开发

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

源码开发模式公开 Web `3000` 和 API `8000`。停止服务不会删除 `data/`：

```bash
docker compose -f docker-compose.dev.yml down
```

## 升级与回滚

生产环境固定使用 `.env` 中的 `CLOUDSITE_IMAGE_TAG`。升级前先备份：

```bash
bash scripts/backup.sh
docker compose pull
docker compose up -d
curl -f http://127.0.0.1:3000/
```

如果升级失败，把 `.env` 中的镜像标签改回原版本，再执行：

```bash
docker compose pull
docker compose up -d
```

数据库需要回滚时，再使用升级前备份恢复。完整步骤与验证清单见 [`docs/部署升级与备份.md`](docs/部署升级与备份.md)。

## 常用操作

```bash
docker compose ps
docker compose logs -f --tail=200
docker compose restart
docker compose down
```

请勿执行 `docker compose down -v`，也不要在未备份时删除 `data/`。

## 开发与验证

```bash
# 后端测试
docker compose -f docker-compose.dev.yml run --rm api pytest

# 前端类型检查与生产构建
docker compose -f docker-compose.dev.yml run --rm web npm run lint
docker compose -f docker-compose.dev.yml run --rm web npm run build

# Compose 静态校验
docker compose config
docker compose -f docker-compose.traefik.yml config

# 两个源码镜像构建冒烟
docker compose -f docker-compose.dev.yml build
```

GitHub Actions 对 pull request 和主分支执行以上质量检查；只有全部通过后，主分支或 `v*` 标签才发布 GHCR 镜像：

- `ghcr.io/nathanxiangang-web/cloudsite-api`
- `ghcr.io/nathanxiangang-web/cloudsite-web`

## 同步安全模型

- 新实例和未完成首次同步的实例继续运行原有首次完整同步；Rolling 迁移前必须同时存在成功同步记录和有效 Folder 索引。
- 迁移仅创建 Cycle、Window 和 Folder 队列状态，保留 Folder、Resource、合集、配置以及首次同步完成时间，不发起 AList 请求。
- 同一时间只允许一个同步任务运行；Rolling Window 对计划内目录逐个校验并持久化进度，服务重启后从未完成项继续。
- 目录扫描失败时保留旧索引，不把“没扫到”当作删除。
- 第一个独立 Cycle 未见对象：`active → suspected_missing`；下一独立 Cycle 仍未见：`suspected_missing → missing`。
- 对象在确认前重新出现时，状态、缺失次数和候选时间全部恢复。
- 大规模候选新增/缺失触发 Scope 级零写入保护，只保存审计结果，不写入新项也不改变旧项。
- `index.db` 丢失但 `state.db` 身份仍在时进入 `INDEX_RECOVERY`，不会退回首次安装或覆盖首次同步历史。

## 安全说明

- `.env`、`data/`、备份、预览缓存和日志均被 `.gitignore` 排除。
- `CLOUDSITE_MASTER_KEY` 或其回退密钥一旦用于保存 AList 凭据，不可随意更换。
- AList 账号应独立创建并遵循最小权限；不要把浏览器登录令牌写进 `.env`。
- `CLOUDSITE_TRUSTED_PROXY_CIDRS` 只应包含实际反向代理网段，不能把普通客户端所在的整个局域网加入可信代理。
- 下载入口由 AList 临时签名，失效时可在后台“下载诊断”重新测试。

## 许可证

本项目采用仓库中的 [LICENSE](LICENSE) 许可。
