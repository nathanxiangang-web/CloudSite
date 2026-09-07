#!/usr/bin/env bash
# CloudSite 备份加固隔离测试。
set -euo pipefail

FAIL=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; FAIL=1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-backup-test.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

setup_fixture() {
  local root="$1"
  mkdir -p "$root/data" "$root/scripts"
  cp "$ROOT/scripts/backup.sh" "$root/scripts/backup.sh"
  cp "$ROOT/scripts/verify-backup.sh" "$root/scripts/verify-backup.sh"
  cp "$ROOT/scripts/restore.sh" "$root/scripts/restore.sh"
  printf "CLOUDSITE_SECRET_KEY=test-invalid-placeholder\n" > "$root/.env"
  python3 - "$root/data/state.db" "$root/data/index.db" <<'PYFIX'
import sqlite3, sys
for path in sys.argv[1:]:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t (id) VALUES (1)")
    conn.commit()
    conn.close()
PYFIX
  cat > "$root/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
}

setup_fixture "$WORK/proj"
OUT="$WORK/backup.tar.gz"
(cd "$WORK/proj" && bash scripts/backup.sh "$OUT") >&2
if [[ -f "$OUT" ]]; then
  perm="$(stat -c "%a" "$OUT")"
  [[ "$perm" == "600" ]] && pass "archive permission 0600" || fail "archive permission expected 600 got $perm"
else
  fail "archive not created"
fi
if ! ls -a "$WORK/proj/data" | grep -q "^\\.cloudsite-backup-"; then
  pass "no leftover temp db (normal path)"
else
  fail "leftover temp db in data/"
fi

if bash "$ROOT/scripts/verify-backup.sh" "$OUT" >&2; then
  pass "verify valid archive"
else
  fail "verify valid archive rejected"
fi

Unsafe="$WORK/unsafe.tar.gz"
python3 - "$Unsafe" <<'PYUNSAFE'
import tarfile, io, sys
with tarfile.open(sys.argv[1], "w:gz") as t:
    info = tarfile.TarInfo("../escape.txt")
    data = b"x"
    info.size = len(data)
    t.addfile(info, io.BytesIO(data))
PYUNSAFE
if bash "$ROOT/scripts/verify-backup.sh" "$Unsafe" >&2; then
  fail "unsafe path accepted"
else
  pass "unsafe path rejected"
fi

mkdir -p "$WORK/missing-stage/data"
python3 - "$WORK/missing-stage/data/state.db" <<'PYMISS'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE t(id)"); c.commit(); c.close()
PYMISS
tar -czf "$WORK/missing.tar.gz" -C "$WORK/missing-stage" .
if bash "$ROOT/scripts/verify-backup.sh" "$WORK/missing.tar.gz" >&2; then
  fail "missing files accepted"
else
  pass "missing files rejected"
fi

mkdir -p "$WORK/corrupt-stage/data"
printf "CLOUDSITE_SECRET_KEY=test\n" > "$WORK/corrupt-stage/.env"
python3 - "$WORK/corrupt-stage/data/state.db" "$WORK/corrupt-stage/data/index.db" <<'PYCORR'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p); c.execute("CREATE TABLE t(id)"); c.commit(); c.close()
PYCORR
printf "corrupt" > "$WORK/corrupt-stage/data/state.db"
tar -czf "$WORK/corrupt.tar.gz" -C "$WORK/corrupt-stage" .
if bash "$ROOT/scripts/verify-backup.sh" "$WORK/corrupt.tar.gz" >&2; then
  fail "corrupt db accepted"
else
  pass "corrupt db rejected"
fi

mkdir -p "$WORK/restore-target/data"
echo existing > "$WORK/restore-target/.env"
if bash "$ROOT/scripts/restore.sh" "$OUT" --target "$WORK/restore-target" >&2; then
  fail "restore overwrote without --force"
else
  pass "restore default refuses overwrite"
fi

FT="$WORK/force-target"
mkdir -p "$FT/data"
echo old-data > "$FT/data/old.txt"
echo old-env > "$FT/.env"
bash "$ROOT/scripts/restore.sh" "$OUT" --target "$FT" --force >&2
rollback_count=$(find "$FT" -maxdepth 1 -name ".restore-rollback-*" -type d | wc -l)
[[ "$rollback_count" == "1" ]] && pass "force restore one rollback" || fail "force restore rollback count $rollback_count"
rollback=$(find "$FT" -maxdepth 1 -name ".restore-rollback-*" -type d | head -1)
[[ -f "$rollback/data/old.txt" ]] && pass "rollback preserved old data" || fail "rollback missing old data"
[[ -f "$rollback/.env" ]] && pass "rollback preserved old env" || fail "rollback missing old env"
fok=1
python3 - "$FT/data/state.db" "$FT/data/index.db" <<'PYF' || fok=0
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise SystemExit(1)
    c.close()
PYF
[[ "$fok" == "1" ]] && pass "force restored dbs quick_check ok" || fail "force restored dbs quick_check failed"
if diff -q "$WORK/proj/.env" "$FT/.env" >/dev/null 2>&1; then
  pass "force restored .env from backup"
else
  fail "force restored .env not from backup"
fi

RT="$WORK/restore-clean"
mkdir -p "$RT"
bash "$ROOT/scripts/restore.sh" "$OUT" --target "$RT" >&2
ok=1
python3 - "$RT/data/state.db" "$RT/data/index.db" <<'PYREST' || ok=0
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise SystemExit(1)
    c.close()
PYREST
[[ "$ok" == "1" ]] && pass "restored dbs quick_check ok" || fail "restored dbs quick_check failed"
if diff -q "$WORK/proj/.env" "$RT/.env" >/dev/null 2>&1; then
  pass "restored .env matches fixture"
else
  fail "restored .env mismatch"
fi

setup_fixture "$WORK/proj-fail"
mkdir -p "$WORK/fake-bin"
cat > "$WORK/fake-bin/docker" <<'DOCKER'
#!/usr/bin/env bash
if [[ "$1" == "compose" && "$4" == "ps" ]]; then
  echo "fake-api-container"
  exit 0
fi
if [[ "$1" == "compose" && "$4" == "exec" ]]; then
  eval "cmd=\${$#}"
  temp_path=$(printf '%s' "$cmd" | sed -n "s#.*dst=sqlite3\.connect('\(/data/[^']*\)').*#\1#p")
  if [[ -n "$temp_path" ]]; then
    touch ".$temp_path"
    echo ".$temp_path" >> "$FAKE_DOCKER_LOG"
  fi
  exit 1
fi
exit 0
DOCKER
chmod +x "$WORK/fake-bin/docker"
FAKE_DOCKER_LOG="$WORK/fake-docker.log"
rm -f "$FAKE_DOCKER_LOG"
export FAKE_DOCKER_LOG
FAIL_OUT="$WORK/fail-backup.tar.gz"
if (cd "$WORK/proj-fail" && PATH="$WORK/fake-bin:$PATH" bash scripts/backup.sh "$FAIL_OUT") >&2; then
  fail "simulated online backup should have failed"
else
  pass "simulated online backup failed as expected"
if [[ -s "$FAKE_DOCKER_LOG" ]]; then
  pass "fake docker created temp db"
else
  fail "fake docker did not create temp db"
fi
fi
if ! ls -a "$WORK/proj-fail/data" | grep -q "^\\.cloudsite-backup-"; then
  pass "no leftover temp db (failure path)"
else
  fail "leftover temp db after failure"
fi

if [[ "$FAIL" == "0" ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "SOME TESTS FAILED" >&2
  exit 1
fi
