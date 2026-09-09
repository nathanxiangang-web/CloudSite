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
# Relative paths resolve from $base_dir and must stay strictly below it.
# Fail closed on empty explicit values, shell-expansion syntax, quotes, control
# characters, leading ~, traversal, the base directory itself, and filesystem root.
# Never source or eval the .env file.
# Args: base_dir env_file context  (context = backup|restore; restore treats an
# absolute path read from env_file as untrusted and rejects it before any move/copy).
resolve_data_path() {
  local base_dir="$1"
  local env_file="${2:-}"
  local context="${3:-backup}"
  local raw=""
  local source="absent"
  local err_tag="backup failed"
  [[ "$context" == "restore" ]] && err_tag="restore failed"

  if [[ -n "${CLOUDSITE_DATA_PATH+x}" ]]; then
    raw="$CLOUDSITE_DATA_PATH"
    source="exported"
  elif [[ -n "$env_file" && -f "$env_file" ]]; then
    local line trimmed
    while IFS= read -r line || [[ -n "$line" ]]; do
      trimmed="${line#"${line%%[![:space:]]*}"}"
      [[ -z "$trimmed" || "$trimmed" == \#* ]] && continue
      case "$trimmed" in
        CLOUDSITE_DATA_PATH=*)
          raw="${trimmed#CLOUDSITE_DATA_PATH=}"
          source="envfile"
          break
          ;;
      esac
    done < "$env_file"
  fi

  if [[ "$source" == "absent" ]]; then
    raw="./data"
    source="default"
  fi

  if [[ "$source" != "default" ]]; then
    if [[ -z "$raw" ]]; then
      echo "$err_tag: CLOUDSITE_DATA_PATH is set to an empty value" >&2
      exit 1
    fi
    case "$raw" in
      '~'*|*'"'*|*"'"*|*'$'*|*'`'*)
        echo "$err_tag: CLOUDSITE_DATA_PATH has unsupported syntax: $raw" >&2
        exit 1
        ;;
    esac
    if printf '%s' "$raw" | LC_ALL=C grep -q '[[:cntrl:]]'; then
      echo "$err_tag: CLOUDSITE_DATA_PATH contains control characters" >&2
      exit 1
    fi
  fi

  if [[ "$raw" == /* ]]; then
    if [[ "$source" == "envfile" && "$context" == "restore" ]]; then
      echo "$err_tag: absolute CLOUDSITE_DATA_PATH from archived .env rejected: $raw" >&2
      exit 1
    fi
    local absolute_real
    absolute_real="$(realpath -m -- "$raw")"
    if [[ "$absolute_real" == "/" ]]; then
      echo "$err_tag: CLOUDSITE_DATA_PATH cannot be filesystem root" >&2
      exit 1
    fi
    printf '%s' "$absolute_real"
    return
  fi

  local base_real cand_real
  base_real="$(realpath -m -- "$base_dir")"
  cand_real="$(realpath -m -- "$base_real/$raw")"
  if [[ "$cand_real" == "$base_real" || "$cand_real" == "/" ]]; then
    echo "$err_tag: CLOUDSITE_DATA_PATH cannot be base dir or root: $raw" >&2
    exit 1
  fi
  case "$cand_real" in
    "$base_real"/*) ;;
    *)
      echo "$err_tag: CLOUDSITE_DATA_PATH escapes base directory: $raw" >&2
      exit 1
      ;;
  esac
  printf '%s' "$cand_real"
}

bash "$ROOT/scripts/verify-backup.sh" "$BACKUP"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-restore.XXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT
tar -xzf "$BACKUP" -C "$STAGE"

# 归档保持可移植 data/ 布局；恢复目标切换到目标项目配置的宿主数据目录。
DATA_PATH="$(resolve_data_path "$TARGET" "$STAGE/.env" "restore")"

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
