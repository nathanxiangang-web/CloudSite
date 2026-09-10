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

# 检测 API 运行状态：running / stopped / unknown。
# command -v docker 不存在 → stopped（无 Docker 环境，视为未运行）。
# docker compose ps 退出非 0 → unknown（无法判断，调用方须失败）。
# 退出 0 且输出非空 → running；退出 0 且输出空 → stopped。
detect_api_state() {
  local compose_file="$1"
  if ! command -v docker >/dev/null 2>&1; then
    printf "stopped"
    return
  fi
  local out rc
  out="$(docker compose -f "$compose_file" ps --status running -q api 2>/dev/null)" && rc=0 || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    printf "unknown"
    return
  fi
  if [[ -n "$out" ]]; then
    printf "running"
  else
    printf "stopped"
  fi
}

# 一致性备份单个数据库到目标文件。
# 优先 python3 sqlite3.backup()（产出含已提交 WAL 的单文件）；
# 否则 sqlite3 .backup；否则复制 db+wal+shm（WAL 处理）。
consistent_backup_db() {
  local source="$1" dest="$2"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$source" "$dest" <<'PYBK'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PYBK
  elif command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$source" ".backup '$dest'"
  else
    cp -p "$source" "$dest"
    [[ -f "$source-wal" ]] && cp -p "$source-wal" "$dest-wal"
    [[ -f "$source-shm" ]] && cp -p "$source-shm" "$dest-shm"
  fi
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

# 先复制非数据库文件；数据库文件随后用一致性备份覆盖。
# 归档保持可移植的 data/ 布局，仅读取来源切换到配置的宿主数据目录。
tar \
  --exclude='*.db' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  -C "$DATA_PATH" -cf - . | tar -C "$STAGE/data" -xf -

COMPOSE_FILE="$ROOT/docker-compose.yml"
API_STATE="$(detect_api_state "$COMPOSE_FILE")"
if [[ "$API_STATE" == "unknown" ]]; then
  echo "备份失败：无法判断 API 运行状态（docker compose ps 异常）。请确认 Docker 可用或先 docker compose down。" >&2
  exit 1
fi

BACKUP_METHOD="offline"
for db_name in state.db index.db; do
  source_db="$DATA_PATH/$db_name"
  [[ -f "$source_db" ]] || continue
  if [[ "$API_STATE" == "running" ]]; then
    BACKUP_METHOD="online"
    temp_name=".cloudsite-backup-$STAMP-$db_name"
    temp_path="$DATA_PATH/$temp_name"
    TEMP_DBS+=("$temp_path")
    if ! docker compose -f "$COMPOSE_FILE" exec -T api python -c \
      "import sqlite3; src=sqlite3.connect('/data/$db_name'); dst=sqlite3.connect('/data/$temp_name'); src.backup(dst); dst.close(); src.close()"; then
      echo "备份失败：容器内在线备份 $db_name 失败。" >&2
      exit 1
    fi
    cp -p "$temp_path" "$STAGE/data/$db_name"
    rm -f -- "$temp_path"
  else
    consistent_backup_db "$source_db" "$STAGE/data/$db_name"
  fi
done

# 生成备份 manifest：记录版本/schema/方法/时间/文件校验/验证级别。
# 不读取或写入任何密钥值（仅访问数据文件与 schema_version）。
if command -v python3 >/dev/null 2>&1; then
  python3 - "$STAGE" "$BACKUP_METHOD" "$STAMP" <<'PYMAN'
import sqlite3, sys, os, json, hashlib

stage, method, stamp = sys.argv[1], sys.argv[2], sys.argv[3]

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def schema_version(path):
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "system_settings" in tables:
            row = conn.execute("SELECT value FROM system_settings WHERE key='schema_version'").fetchone()
            conn.close()
            return row[0] if row else None
        conn.close()
    except Exception:
        pass
    return None

databases = {}
for db_name in ("state.db", "index.db"):
    p = os.path.join(stage, "data", db_name)
    if os.path.isfile(p):
        databases[db_name] = {
            "sha256": sha256_file(p),
            "size": os.path.getsize(p),
            "schema_version": schema_version(p),
        }

manifest = {
    "backup_version": "2.0",
    "created_at": stamp,
    "method": method,
    "databases": databases,
    "verification_level": "quick_check+sentinels+relations",
}
with open(os.path.join(stage, "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
PYMAN
else
  manifest="$STAGE/manifest.json"
  {
    echo "{"
    echo "  \"backup_version\": \"2.0\","
    echo "  \"created_at\": \"$STAMP\","
    echo "  \"method\": \"$BACKUP_METHOD\","
    echo "  \"databases\": {"
    first=1
    for db_name in state.db index.db; do
      [[ -f "$STAGE/data/$db_name" ]] || continue
      [[ "$first" -eq 1 ]] || echo ","
      first=0
      sha="$(sha256sum "$STAGE/data/$db_name" | awk '{print $1}')"
      size="$(stat -c %s "$STAGE/data/$db_name")"
      printf '    "%s": {"sha256": "%s", "size": %s}' "$db_name" "$sha" "$size"
    done
    echo ""
    echo "  },"
    echo "  \"verification_level\": \"quick_check+sentinels+relations\""
    echo "}"
  } > "$manifest"
fi

mkdir -p "$(dirname "$OUT")"
tar -czf "$OUT" -C "$STAGE" .
chmod 0600 "$OUT"
bash "$ROOT/scripts/verify-backup.sh" "$OUT"
echo "备份完成：$OUT（数据来源：$DATA_PATH，方法：$BACKUP_METHOD）"
