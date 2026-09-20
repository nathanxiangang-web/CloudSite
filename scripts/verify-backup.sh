#!/usr/bin/env bash
# 验证备份结构、SQLite 完整性、业务哨兵与 manifest 校验。
# 验证器选择：宿主 python3 > 镜像内 python（docker run）> 明确失败。
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
    /*|../* |*/../*)
      echo "验证失败：归档包含不安全路径：$member" >&2
      exit 1
      ;;
  esac
done < <(tar -tzf "$BACKUP")

tar -xzf "$BACKUP" -C "$STAGE"
[[ -f "$STAGE/.env" ]] || { echo "验证失败：缺少 .env" >&2; exit 1; }
[[ -f "$STAGE/data/state.db" ]] || { echo "验证失败：缺少 data/state.db" >&2; exit 1; }
[[ -f "$STAGE/data/index.db" ]] || { echo "验证失败：缺少 data/index.db" >&2; exit 1; }

# 验证器 Python 代码：quick_check + 外键 + 业务哨兵 + manifest 校验。
# 同时用于宿主 python3 和镜像内 python（通过挂载执行）。
cat > "$STAGE/verify_content.py" <<'PYVERIFY'
import sqlite3, sys, os, json, hashlib

errors = []
state_db = sys.argv[1]
index_db = sys.argv[2]
manifest_path = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None

def query(path, sql):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()

def tables_of(path):
    return {r[0] for r in query(path, "SELECT name FROM sqlite_master WHERE type='table'")}

for label, path in (("state.db", state_db), ("index.db", index_db)):
    result = query(path, "PRAGMA quick_check")[0][0]
    if result != "ok":
        errors.append(f"{label} quick_check: {result}")

for label, path in (("state.db", state_db), ("index.db", index_db)):
    for row in query(path, "PRAGMA foreign_key_check"):
        errors.append(f"{label} FK violation: {row}")

state_tables = tables_of(state_db)
index_tables = tables_of(index_db)

if "users" in state_tables:
    try:
        query(state_db, "SELECT COUNT(*) FROM users")
    except Exception as e:
        errors.append(f"users sentinel: {e}")

if "system_settings" in state_tables:
    try:
        query(state_db, "SELECT COUNT(*) FROM system_settings")
    except Exception as e:
        errors.append(f"system_settings sentinel: {e}")

if "resources" in index_tables and "folders" in index_tables:
    res_cols = {r[1] for r in query(index_db, "PRAGMA table_info(resources)")}
    if "parent_id" in res_cols:
        orphans = query(index_db,
            "SELECT r.id, r.parent_id FROM resources r "
            "WHERE r.parent_id IS NOT NULL AND r.parent_id != '' "
            "AND NOT EXISTS (SELECT 1 FROM folders f WHERE f.id = r.parent_id)")
        if orphans:
            errors.append(f"orphan resources (parent_id not in folders): {orphans[:5]}")

if "shares" in index_tables:
    try:
        query(index_db, "SELECT COUNT(*) FROM shares")
    except Exception as e:
        errors.append(f"shares sentinel: {e}")

if manifest_path and os.path.isfile(manifest_path):
    try:
        manifest = json.load(open(manifest_path))
        base = os.path.dirname(manifest_path)
        for db_name, info in manifest.get("databases", {}).items():
            p = os.path.join(base, "data", db_name)
            if not os.path.isfile(p):
                errors.append(f"manifest references missing {db_name}")
                continue
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            if h.hexdigest() != info.get("sha256"):
                errors.append(f"manifest sha256 mismatch for {db_name}")
    except Exception as e:
        errors.append(f"manifest validation: {e}")

if errors:
    for e in errors:
        print("VERIFY FAIL: " + e, file=sys.stderr)
    raise SystemExit(1)
PYVERIFY

if command -v python3 >/dev/null 2>&1; then
  python3 "$STAGE/verify_content.py" "$STAGE/data/state.db" "$STAGE/data/index.db" "$STAGE/manifest.json"
elif command -v docker >/dev/null 2>&1; then
  IMG="${CLOUDSITE_VERIFY_PYTHON_IMAGE:-python:3-slim}"
  if ! docker run --rm -v "$STAGE:/verify:ro" "$IMG" \
      python3 /verify/verify_content.py /verify/data/state.db /verify/data/index.db /verify/manifest.json; then
    echo "验证失败：镜像内验证器不可用或验证未通过。" >&2
    exit 1
  fi
else
  echo "验证失败：无可用验证器（宿主无 python3 且无 docker 运行镜像内验证器）。" >&2
  exit 1
fi

echo "备份验证通过：$BACKUP"
