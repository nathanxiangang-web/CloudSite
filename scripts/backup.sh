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

if [[ ! -f "$ROOT/.env" ]]; then
  echo "备份失败：未找到 $ROOT/.env" >&2
  exit 1
fi
if [[ ! -d "$ROOT/data" ]]; then
  echo "备份失败：未找到 $ROOT/data" >&2
  exit 1
fi

mkdir -p "$STAGE/data"
cp -p "$ROOT/.env" "$STAGE/.env"

# 先复制非数据库文件；数据库文件随后用 SQLite online backup 覆盖。
tar \
  --exclude='*.db' \
  --exclude='*.db-wal' \
  --exclude='*.db-shm' \
  -C "$ROOT/data" -cf - . | tar -C "$STAGE/data" -xf -

api_running="$(docker compose -f "$ROOT/docker-compose.yml" ps --status running -q api 2>/dev/null || true)"
for db_name in state.db index.db; do
  source_db="$ROOT/data/$db_name"
  [[ -f "$source_db" ]] || continue
  if [[ -n "$api_running" ]]; then
    temp_name=".cloudsite-backup-$STAMP-$db_name"
    temp_path="$ROOT/data/$temp_name"
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
echo "备份完成：$OUT"
