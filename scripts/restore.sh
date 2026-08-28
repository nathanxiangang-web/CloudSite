#!/usr/bin/env bash
# CloudSite 恢复：将备份中的 data/ 与 .env 解包回项目根目录。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP="${1:?用法: scripts/restore.sh <backup.tar.gz>}"
tar -xzf "$BACKUP" -C "$ROOT" data .env
echo "恢复完成。请检查 .env 后重新启动服务（docker compose up -d）。"
