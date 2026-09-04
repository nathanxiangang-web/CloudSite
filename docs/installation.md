# CloudSite 安装指南

> 对应 1.0 开发文档第 70 节：在线 Docker、Traefik、离线、AMD64、ARM64。

## 前置要求

- Docker Engine
- Docker Compose Plugin
- 服务器无需安装 Node.js 或 Python

## 一、在线 Docker 部署

```bash
git clone https://github.com/nathanxiangang-web/CloudSite.git
cd CloudSite
cp .env.example .env
```

编辑 `.env`，至少替换 `CLOUDSITE_SECRET_KEY`：

```bash
# 生成密钥
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

启动：

```bash
docker compose up -d
docker compose ps
```

打开 `http://服务器IP:3000`。默认只公开 Web 端口 3000，API 在内部网络提供服务，数据保存在 `./data`。

## 二、Traefik HTTPS 部署

在 `.env` 中设置：

```dotenv
CLOUDSITE_DOMAIN=cloud.example.com
TRAEFIK_NETWORK=my-servers_app-net
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_CERT_RESOLVER=myresolver
```

确认外部网络已存在：

```bash
docker network inspect "$TRAEFIK_NETWORK"
```

启动 Traefik 配置：

```bash
docker compose -f docker-compose.traefik.yml up -d
```

`docker-compose.traefik.yml` 不映射宿主机端口，由现有 Traefik 通过指定网络访问 Web 容器。

## 三、离线部署

没有外网、不能访问 GHCR 的服务器，从 GitHub Releases 下载离线附件：

```
cloudsite-api-v{VERSION}-linux-amd64.tar.gz
cloudsite-api-v{VERSION}-linux-arm64.tar.gz
cloudsite-web-v{VERSION}-linux-amd64.tar.gz
cloudsite-web-v{VERSION}-linux-arm64.tar.gz
cloudsite-v{VERSION}-offline-deploy.zip
SHA256SUMS.txt
```

### 校验与导入

```bash
sha256sum -c SHA256SUMS.txt
arch=arm64  # x86_64 服务器改为 amd64
gzip -dc "cloudsite-api-v${VERSION}-linux-${arch}.tar.gz" | docker load
gzip -dc "cloudsite-web-v${VERSION}-linux-${arch}.tar.gz" | docker load
```

### 启动

```bash
unzip cloudsite-v${VERSION}-offline-deploy.zip -d CloudSite
cd CloudSite
cp .env.example .env
# 编辑 .env，至少替换 CLOUDSITE_SECRET_KEY
docker compose -f docker-compose.yml -f docker-compose.offline.yml up -d --wait
```

完整传输、安装、验收步骤见 [离线安装](离线安装.md)。

## 四、架构选择

| 架构 | 镜像 | 说明 |
|------|------|------|
| `linux/amd64` | `*-linux-amd64.tar.gz` | x86_64 服务器（大多数云服务器） |
| `linux/arm64` | `*-linux-arm64.tar.gz` | ARM 服务器（树莓派、Apple Silicon） |

GHCR 多架构 Manifest 包含两种架构，`docker compose pull` 自动选择匹配当前服务器的架构。

## 五、首次配置

1. 访问站点，进入后台
2. **系统设置** → 配置 AList 地址、账号、密码
3. **内容根** → 添加要索引的 AList 目录（如 `/软件`、`/图片`）
4. **同步** → 触发首次同步，等待索引完成
5. **站点设置** → 配置站点名称、投稿邮箱等

## 六、升级

```bash
# 1. 备份
bash scripts/backup.sh

# 2. 更新镜像标签
# 编辑 .env 中 CLOUDSITE_IMAGE_TAG 为新版本

# 3. 拉取并重启
docker compose pull
docker compose up -d

# 4. 验证
curl -f http://127.0.0.1:3000/
curl -fsS http://127.0.0.1:8000/api/health
```

升级会自动执行 schema migration。如果检测到旧 schema_version，会自动创建迁移前快照到 `data/.codex-backups/pre-migration/`。

完整升级步骤见 [部署升级与备份](部署升级与备份.md)。

## 七、回滚

```bash
# 1. 恢复旧镜像标签
# 编辑 .env 中 CLOUDSITE_IMAGE_TAG 改回原版本

# 2. 拉取并重启
docker compose pull
docker compose up -d

# 3. 如需恢复数据库
docker compose down
bash scripts/restore.sh <backup.tar.gz> --force
docker compose up -d
```

**注意**：代码回滚 ≠ 数据库自动向下兼容。标准回滚 = 恢复旧镜像 + 恢复升级前数据库备份。

## 八、本地源码开发

!开发

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

源码开发模式公开 Web `3000` 和 API `8000`。停止不删除 `data/`：

```bash
docker compose -f docker-compose.dev.yml down
```

## 九、常用操作

```bash
docker compose ps              # 查看状态
docker compose logs -f --tail=200  # 查看日志
docker compose restart         # 重启
docker compose down            # 停止
```

**请勿**执行 `docker compose down -v`，也不要在未备份时删除 `data/`。
