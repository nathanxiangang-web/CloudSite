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

# Resolve the host data directory deterministically.
# Precedence: exported CLOUDSITE_DATA_PATH > simple KEY=VALUE in the archive .env > ./data.
# Relative paths resolve from $base_dir. Fail closed on empty or shell-expansion syntax;
# never source or eval the .env file.
resolve_data_path() {
  local base_dir="$1"
  local env_file="${2:-}"
  local raw=""
  if [[ -n "${CLOUDSITE_DATA_PATH:-}" ]]; then
    raw="$CLOUDSITE_DATA_PATH"
  elif [[ -n "$env_file" && -f "$env_file" ]]; then
    local line trimmed
    while IFS= read -r line || [[ -n "$line" ]]; do
      trimmed="${line#"${line%%[![:space:]]*}"}"
      [[ -z "$trimmed" || "$trimmed" == \#* ]] && continue
      case "$trimmed" in
        CLOUDSITE_DATA_PATH=*)
          raw="${trimmed#CLOUDSITE_DATA_PATH=}"
          break
          ;;
      esac
    done < "$env_file"
  fi
  [[ -z "$raw" ]] && raw="./data"
  case "$raw" in
    *'$'*|*'`'*)
      echo "恢复失败：CLOUDSITE_DATA_PATH 含不被支持的语法：$raw" >&2
      exit 1
      ;;
  esac
  if [[ "$raw" == /* ]]; then
    printf '%s' "$raw"
  else
    printf '%s/%s' "$base_dir" "$raw"
  fi
}

bash "$ROOT/scripts/verify-backup.sh" "$BACKUP"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-restore.XXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT
tar -xzf "$BACKUP" -C "$STAGE"

# 归档保持可移植 data/ 布局；恢复目标切换到目标项目配置的宿主数据目录。
DATA_PATH="$(resolve_data_path "$TARGET" "$STAGE/.env")"

if [[ "$TARGET" == "$ROOT" ]]; then
  running="$(docker compose -f "$ROOT/docker-compose.yml" ps --status running -q 2>/dev/null || true)"
  if [[ -n "$running" ]]; then
    echo "恢复失败：CloudSite 仍在运行。请先执行 docker compose down，再重试。" >&2
    exit 1
  fi
fi

if [[ -e "$DATA_PATH" || -e "$TARGET/.env" ]]; then
  if [[ "$FORCE" -ne 1 ]]; then
    echo "恢复失败：目标已有数据目录或 .env；确认覆盖时请增加 --force。" >&2
    exit 1
  fi
  rollback="$TARGET/.restore-rollback-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$rollback"
  [[ -e "$DATA_PATH" ]] && mv "$DATA_PATH" "$rollback/data"
  [[ -e "$TARGET/.env" ]] && mv "$TARGET/.env" "$rollback/.env"
  echo "原数据已保留：$rollback"
fi

mkdir -p "$TARGET"
mkdir -p "$(dirname "$DATA_PATH")"
cp -a "$STAGE/data" "$DATA_PATH"
cp -p "$STAGE/.env" "$TARGET/.env"
echo "恢复完成：数据目录 $DATA_PATH，项目目录 $TARGET。检查 .env 后重新启动服务。"
