# CloudSite

CloudSite 将 AList 中的网盘目录转换为可浏览、搜索、预览和分享的资源网站，并通过 AList 原生下载入口提供浏览器 302 直连下载。

> 发布源码不包含 AList 账号、访问令牌、`.env`、数据库、索引、日志、依赖目录或构建产物。

## 功能概览

- 使用 AList 凭据连接网盘，配置在服务端加密保存。
- 扫描任意深度目录，按软件、图片、视频、文档等类型浏览和搜索。
- 支持图片、视频、PDF、文本、Markdown 和常见 Office 文档预览。
- 登录用户可从文件详情创建 4 位分享码或免提取码直下分享，并管理自己的分享；接收者无需登录。分享支持固定有效期与查看/下载统计，每个分享最多成功下载 404 次。
- 支持独立的前台用户注册、强制登录、账户安全与后台用户完整生命周期管理；用户名为 2～16 位字母、数字、下划线或短横线，普通用户身份不与 AList 管理员身份混用。
- 资源下载由 `/d/{resource_id}` 解析 Resource，向 AList 获取文件信息及签名，构造 AList Native `/d/` 下载入口并返回 HTTP 302。
- 下载按真实客户端 IP 固定执行滑动 60 秒最多 5 次、第 6 次等待 60 秒；状态持久化在 `state.db`，刷新页面或重启 API 均不能绕过。
- 0.3.0 起 Resource 使用持久身份注册表：已有 ID 原样保留，新资源使用随机 Stable ID，可靠 Rename / Move 不改变资源链接，Copy 与歧义场景采用保守策略。
- 登录用户可在 `/submit` 生成发送至 `nathxo@outlook.com` 的标准投稿邮件；CloudSite 不接收用户上传、不连接 SMTP、不给普通用户 AList 写权限。
- CloudSite 不解析最终 Storage `raw_url`、不代理文件主体，也不按文件大小选择下载策略。
- 内置后台概览、内容索引、合集、分享、下载诊断、站点设置、同步历史和 AList 后台认证；站点设置可自定义桌面分享页右侧展示图。
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

除登录、注册和 `/s/{token}` 匿名分享网关外，前台页面、资源接口、预览和普通下载均要求有效 CloudSite 用户登录。所有分享模式都不要求 CloudSite 账号登录：无分享码模式直接下载，分享码模式验证 4 位分享码后只获得当前分享路径下的短时票据，不能访问站内其他资源；管理后台继续使用独立的 AList 管理员认证。

首次进入后台后，在“系统设置”中配置 AList 地址和独立账号，再配置内容根并执行同步。

## 离线安装

没有外网、不能访问 GHCR 的服务器，请从 GitHub Releases 下载当前版本的离线附件，不要执行 `docker compose pull`：

- `cloudsite-api-v0.5.1-linux-amd64.tar.gz`
- `cloudsite-api-v0.5.1-linux-arm64.tar.gz`
- `cloudsite-web-v0.5.1-linux-amd64.tar.gz`
- `cloudsite-web-v0.5.1-linux-arm64.tar.gz`
- `cloudsite-v0.5.1-offline-deploy.zip`
- `SHA256SUMS.txt`

在联网电脑下载并校验附件，复制到离线服务器后导入两个镜像，再使用离线 Compose 覆盖文件启动：

```bash
sha256sum -c SHA256SUMS.txt
arch=arm64 # x86_64 服务器改为 amd64
gzip -dc "cloudsite-api-v0.5.1-linux-${arch}.tar.gz" | docker load
gzip -dc "cloudsite-web-v0.5.1-linux-${arch}.tar.gz" | docker load
unzip cloudsite-v0.5.1-offline-deploy.zip -d CloudSite
cd CloudSite
cp .env.example .env
# 编辑 .env，至少替换 CLOUDSITE_SECRET_KEY
docker compose -f docker-compose.yml -f docker-compose.offline.yml config --images
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d --wait
```

离线镜像同时提供 `linux/amd64` 与 `linux/arm64`，目标服务器仍需事先安装 Docker Engine 与 Docker Compose Plugin。完整传输、安装、验收和离线升级步骤见 [`docs/离线安装.md`](docs/离线安装.md)。

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

`v*` 标签还会在镜像发布完成后自动生成两个 `linux/amd64` 离线镜像包、离线部署压缩包和 `SHA256SUMS.txt`，并上传到同版本 GitHub Release。标签版本必须与 API、Web 版本号一致，否则发布会被拒绝。

## 同步安全模型

- 新实例和未完成首次同步的实例继续运行原有首次完整同步；Rolling 迁移前必须同时存在成功同步记录和有效 Folder 索引。
- 迁移仅创建 Cycle、Window 和 Folder 队列状态，保留 Folder、Resource、合集、配置以及首次同步完成时间，不发起 AList 请求。
- 同一时间只允许一个同步任务运行；Rolling Window 对计划内目录逐个校验并持久化进度，服务重启后从未完成项继续。
- 目录扫描失败时保留旧索引，不把“没扫到”当作删除。
- 第一个独立 Cycle 未见对象：`active → suspected_missing`；下一独立 Cycle 仍未见：`suspected_missing → missing`。
- 对象在确认前重新出现时，状态、缺失次数和候选时间全部恢复。
- 大规模候选新增/缺失触发 Scope 级零写入保护，只保存审计结果，不写入新项也不改变旧项。
- `index.db` 丢失但 `state.db` 身份仍在时进入 `INDEX_RECOVERY`，不会退回首次安装或覆盖首次同步历史。

## 长期运行与恢复

- 已过期或已撤销超过 7 天的用户 Session 每 6 小时清理一次；有效 Session 不参与清理，`last_seen_at` 最多每 5 分钟写入一次。
- 下载限流记录每 6 小时清理一次，只删除超过 24 小时且不处于封禁期的旧记录。
- `state.db` 保存用户、凭据、站点身份和 Stable Resource ID 注册表，丢失或身份异常时服务拒绝把旧实例当成新安装；它是必须备份的数据。
- `index.db` 保存可重建索引，丢失时进入恢复态，保留 `state.db`，恢复前不重新执行第一次同步。
- 首次升级 0.3.0 时会在数据目录的 `.codex-backups/pre-0.3.0-stable-id/` 创建一次 `state.db` 与 `index.db` 一致性快照；正式升级仍应在容器外另存完整 `data/` 备份。
- FTS 重建使用持久化 dirty 标记；中断后从现有 Folder/Resource 重建，不访问 AList。
- 安全和管理日志建议保留 180 天，普通运行日志建议保留 30～90 天；0.3.0 暂不自动删除 OperationLog，管理员应定期观察行数和数据库体积。

详细恢复、升级与回滚步骤见 [`docs/长期运行与故障恢复.md`](docs/长期运行与故障恢复.md) 和 [`docs/部署升级与备份.md`](docs/部署升级与备份.md)。

## 安全说明

- `.env`、`data/`、备份、预览缓存和日志均被 `.gitignore` 排除。
- `CLOUDSITE_MASTER_KEY` 或其回退密钥一旦用于保存 AList 凭据，不可随意更换。
- AList 账号应独立创建并遵循最小权限；不要把浏览器登录令牌写进 `.env`。
- `CLOUDSITE_TRUSTED_PROXY_CIDRS` 只应包含实际反向代理网段，不能把普通客户端所在的整个局域网加入可信代理。
- 下载入口由 AList 临时签名，失效时可在后台“下载诊断”重新测试。

## 许可证

本项目采用仓库中的 [LICENSE](LICENSE) 许可。
