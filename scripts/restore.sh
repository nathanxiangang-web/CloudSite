#!/usr/bin/env bash
# CloudSite 恢复：默认拒绝覆盖；--force 时先保留本地回滚副本。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP="${1:?用法: scripts/restore.sh <backup.tar.gz> [--target <目录>] [--force]}"
shift
TARGET="$ROOT"
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="${2:?--target 缺少目录}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

bash "$ROOT/scripts/verify-backup.sh" "$BACKUP"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-restore.XXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT
tar -xzf "$BACKUP" -C "$STAGE"

if [[ "$TARGET" == "$ROOT" ]]; then
  running="$(docker compose -f "$ROOT/docker-compose.yml" ps --status running -q 2>/dev/null || true)"
  if [[ -n "$running" ]]; then
    echo "恢复失败：CloudSite 仍在运行。请先执行 docker compose down，再重试。" >&2
    exit 1
  fi
fi

if [[ -e "$TARGET/data" || -e "$TARGET/.env" ]]; then
  if [[ "$FORCE" -ne 1 ]]; then
    echo "恢复失败：目标已有 data/ 或 .env；确认覆盖时请增加 --force。" >&2
    exit 1
  fi
  rollback="$TARGET/.restore-rollback-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$rollback"
  [[ -e "$TARGET/data" ]] && mv "$TARGET/data" "$rollback/data"
  [[ -e "$TARGET/.env" ]] && mv "$TARGET/.env" "$rollback/.env"
  echo "原数据已保留：$rollback"
fi

mkdir -p "$TARGET"
cp -a "$STAGE/data" "$TARGET/data"
cp -p "$STAGE/.env" "$TARGET/.env"
echo "恢复完成：$TARGET。检查 .env 后重新启动服务。"
