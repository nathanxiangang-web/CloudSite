#!/usr/bin/env bash
# CloudSite 一致性备份：在线复制 SQLite，再打包 data/ 与 .env。
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$ROOT/cloudsite-backup-$STAMP.tar.gz}"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-backup.XXXXXX")"
TEMP_DBS=()
cleanup() {
  rm -rf -- "$STAGE"
  if [[ ${#TEMP_DBS[@]} -gt 0 ]]; then
    for db in "${TEMP_DBS[@]}"; do
      rm -f -- "$db"
    done
  fi
}
trap cleanup EXIT

# Resolve the host data directory deterministically.
# Precedence: exported CLOUDSITE_DATA_PATH > simple KEY=VALUE in $ROOT/.env > ./data.
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
      echo "备份失败：CLOUDSITE_DATA_PATH 含不被支持的语法：$raw" >&2
      exit 1
      ;;
  esac
  if [[ "$raw" == /* ]]; then
    printf '%s' "$raw"
  else
    printf '%s/%s' "$base_dir" "$raw"
  fi
}

if [[ ! -f "$ROOT/.env" ]]; then
  echo "备份失败：未找到 $ROOT/.env" >&2
  exit 1
fi

DATA_PATH="$(resolve_data_path "$ROOT" "$ROOT/.env")"
if [[ ! -d "$DATA_PATH" ]]; then
  echo "备份失败：未找到数据目录 $DATA_PATH" >&2
  exit 1
fi

mkdir -p "$STAGE/data"
cp -p "$ROOT/.env" "$STAGE/.env"

# 先复制非数据库文件；数据库文件随后用 SQLite online backup 覆盖。
# 归档保持可移植的 data/ 布局，仅读取来源切换到配置的宿主数据目录。
tar \
  --exclude='*.db' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  -C "$DATA_PATH" -cf - . | tar -C "$STAGE/data" -xf -

api_running="$(docker compose -f "$ROOT/docker-compose.yml" ps --status running -q api 2>/dev/null || true)"
for db_name in state.db index.db; do
  source_db="$DATA_PATH/$db_name"
  [[ -f "$source_db" ]] || continue
  if [[ -n "$api_running" ]]; then
    temp_name=".cloudsite-backup-$STAMP-$db_name"
    temp_path="$DATA_PATH/$temp_name"
    TEMP_DBS+=("$temp_path")
    docker compose -f "$ROOT/docker-compose.yml" exec -T api python -c \
      "import sqlite3; src=sqlite3.connect('/data/$db_name'); dst=sqlite3.connect('/data/$temp_name'); src.backup(dst); dst.close(); src.close()"
    cp -p "$temp_path" "$STAGE/data/$db_name"
    rm -f -- "$temp_path"
  else
    cp -p "$source_db" "$STAGE/data/$db_name"
  fi
done

mkdir -p "$(dirname "$OUT")"
tar -czf "$OUT" -C "$STAGE" .
chmod 0600 "$OUT"
bash "$ROOT/scripts/verify-backup.sh" "$OUT"
echo "备份完成：$OUT（数据来源：$DATA_PATH）"
