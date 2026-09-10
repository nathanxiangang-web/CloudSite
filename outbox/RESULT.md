# work03 M1 备份恢复修复 — 结果

## 修改文件列表
1. `scripts/backup.sh` — Docker 状态检测不吞错；未运行时 SQLite 一致性备份；备份 manifest
2. `scripts/verify-backup.sh` — 验证器缺失明确失败；镜像内验证器 fallback；业务哨兵+关系检查+manifest 校验
3. `scripts/restore.sh` — 运行状态检测不吞错（无法判断时失败）
4. `scripts/tests/test-backup-hardening.sh` — 新增 WAL 一致性、验证器缺失失败、manifest 篡改、Docker 状态未知 4 组测试
5. `scripts/tests/test-backup-content-roundtrip.sh` — 新增孤儿资源关系拒绝、业务归档验证器缺失失败 2 组测试

## 核心改动

### backup.sh
- **Docker 状态不吞错**：新增 `detect_api_state` 函数，区分 `running`/`stopped`/`unknown`。`command -v docker` 不存在视为 `stopped`（无 Docker 环境）；`docker compose ps` 退出非 0 视为 `unknown` → 备份失败。不再用 `2>/dev/null || true` 吞错后当未运行处理（原 12.1 复现的丢 WAL 行根因）。
- **未运行时一致性备份**：新增 `consistent_backup_db`，优先 `python3 sqlite3.backup()`（产出含已提交 WAL 的单文件），否则 `sqlite3 .backup`，否则复制 db+wal+shm。替代原直接 `cp -p` 主库（丢 WAL 行）。
- **运行时容器内备份失败即停**：`docker compose exec` 返回非 0 时备份失败，不再继续。
- **备份 manifest**：生成 `manifest.json`，记录 backup_version/created_at/method/databases(sha256+size+schema_version)/verification_level。不读取或写入任何密钥值（仅访问数据文件与 schema_version）。

### verify-backup.sh
- **验证器缺失明确失败**：宿主无 `python3` 且无 `docker` → 失败（原无 python3 时跳过仍报通过）。
- **镜像内验证器 fallback**：宿主无 python3 时，用 `docker run --rm -v` 临时 python 容器执行验证器（`CLOUDSITE_VERIFY_PYTHON_IMAGE` 可配置）。
- **不只 quick_check**：验证器检查 quick_check + foreign_key_check + 业务哨兵（users/system_settings/shares 表存在则可查询）+ 资源-Catalog 关系（resources.parent_id 引用 folders.id，孤儿关系失败）+ manifest sha256 校验。

### restore.sh
- 运行状态检测不吞错：`docker compose ps` 异常时恢复失败，不再当未运行继续。

## 尚存风险
- 镜像内验证器路径（`docker run python:3-slim`）需拉取镜像，隔离测试未覆盖（需真实 Docker+镜像）；已实现逻辑并覆盖"任何验证器不可用才失败"。
- 独立两库快照不自动等于同时点快照：offline 模式下两库分别 backup API 复制，非单一时间点；state 为权威，索引不一致可重建（符合手册 12.2）。
- manifest 的 schema_version 仅从 state.db system_settings 读取，旧版/空库为 null（不影响校验）。
