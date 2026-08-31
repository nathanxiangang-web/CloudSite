#!/usr/bin/env bash
# 验证备份结构，并在可用时执行 SQLite quick_check。
set -euo pipefail

BACKUP="${1:?用法: scripts/verify-backup.sh <backup.tar.gz>}"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-verify.XXXXXX")"
trap 'rm -rf -- "$STAGE"' EXIT

if [[ ! -f "$BACKUP" ]]; then
  echo "验证失败：备份文件不存在：$BACKUP" >&2
  exit 1
fi

while IFS= read -r member; do
  case "$member" in
    /*|../*|*/../*)
      echo "验证失败：归档包含不安全路径：$member" >&2
      exit 1
      ;;
  esac
done < <(tar -tzf "$BACKUP")

tar -xzf "$BACKUP" -C "$STAGE"
[[ -f "$STAGE/.env" ]] || { echo "验证失败：缺少 .env" >&2; exit 1; }
[[ -f "$STAGE/data/state.db" ]] || { echo "验证失败：缺少 data/state.db" >&2; exit 1; }
[[ -f "$STAGE/data/index.db" ]] || { echo "验证失败：缺少 data/index.db" >&2; exit 1; }

if command -v python3 >/dev/null 2>&1; then
  python3 - "$STAGE/data/state.db" "$STAGE/data/index.db" <<'PY'
import sqlite3
import sys

for path in sys.argv[1:]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    result = connection.execute("PRAGMA quick_check").fetchone()[0]
    connection.close()
    if result != "ok":
        raise SystemExit(f"SQLite quick_check failed for {path}: {result}")
PY
fi

echo "备份验证通过：$BACKUP"
