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

if [[ ! -f "$ROOT/.env" ]]; then
  echo "备份失败：未找到 $ROOT/.env" >&2
  exit 1
fi

DATA_PATH="$(resolve_data_path "$ROOT" "$ROOT/.env" "backup")"
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
