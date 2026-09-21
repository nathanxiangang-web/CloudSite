#!/usr/bin/env bash
set -euo pipefail

# Durable Scan deployment E2E.
#
# This script intentionally restarts the API container. It therefore requires
# an explicit destructive-test opt-in and is intended only for a deployment
# test environment.
#
# Usage:
#   CLOUDSITE_E2E_ALLOW_RESTART=1 \
#   CLOUDSITE_E2E_COMPOSE_FILE=docker-compose.dev.yml \
#   bash scripts/e2e-durable-resume.sh
#
# Preconditions:
#   - the test deployment already has a real provider connection + enabled root
#   - CLOUDSITE_DURABLE_SCAN_ENABLED=true is present in the API container
#   - the provider tree is large enough that a scan can be interrupted
#
# Exit 0 means:
#   1) clean scan completed,
#   2) an active durable scan was interrupted by API restart,
#   3) the same scan run resumed and completed,
#   4) no pending/running/failed dirs remain for that run,
#   5) final production inventory matches the clean-scan inventory fingerprint.

if [[ "${CLOUDSITE_E2E_ALLOW_RESTART:-}" != "1" ]]; then
  echo "REFUSING: this test restarts the API container." >&2
  echo "Set CLOUDSITE_E2E_ALLOW_RESTART=1 only on the deployment test environment." >&2
  exit 2
fi

COMPOSE_FILE="${CLOUDSITE_E2E_COMPOSE_FILE:-docker-compose.dev.yml}"
POLL_SECONDS="${CLOUDSITE_E2E_POLL_SECONDS:-1}"
POLL_ATTEMPTS="${CLOUDSITE_E2E_POLL_ATTEMPTS:-30}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

api_python() {
  compose exec -T api python - "$@"
}

check_durable_flag() {
  api_python <<'PY'
import os
value = os.environ.get("CLOUDSITE_DURABLE_SCAN_ENABLED", "").strip().lower()
if value not in {"1", "true", "yes", "on"}:
    raise SystemExit(
        "CLOUDSITE_DURABLE_SCAN_ENABLED is not enabled inside the API container"
    )
print("durable flag: enabled")
PY
}

check_durable_schema() {
  api_python <<'PY'
import sqlite3

db = sqlite3.connect("/data/state.db")
tables = {
    row[0]
    for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )
}
required_tables = {"index_scan_runs", "index_scan_dirs", "index_scan_entries"}
missing_tables = sorted(required_tables - tables)
if missing_tables:
    raise SystemExit(f"durable scan tables missing: {missing_tables}")

entry_columns = {
    row[1] for row in db.execute("PRAGMA table_info(index_scan_entries)")
}
required_columns = {"dir_path", "path", "parent_path", "resource_id", "metadata_json"}
missing_columns = sorted(required_columns - entry_columns)
if missing_columns:
    raise SystemExit(
        f"durable scan staging schema is not current: missing {missing_columns}"
    )
print("durable schema: ready")
PY
}

assert_no_running_scans() {
  api_python <<'PY'
import sqlite3

db = sqlite3.connect("/data/state.db")
rows = db.execute(
    """
    SELECT id, root_mapping_id, started_at
    FROM index_scan_runs
    WHERE status = 'running'
    ORDER BY started_at
    """
).fetchall()
if rows:
    details = ", ".join(
        f"id={run_id} root={root_id} started={started_at}"
        for run_id, root_id, started_at in rows
    )
    raise SystemExit(
        "refusing to start E2E while durable scans are already running: "
        + details
    )
print("durable preflight: no pre-existing running scans")
PY
}

run_sync() {
  api_python <<'PY'
import asyncio
import json
from cloudsite.tasks.sync import run_indexing_v2_production

result = asyncio.run(run_indexing_v2_production())
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
if result.get("status") != "success":
    raise SystemExit(f"sync was not fully successful: {result!r}")
if not result.get("scan_complete", True):
    raise SystemExit(f"sync did not complete: {result!r}")
PY
}

inventory_fingerprint() {
  api_python <<'PY'
import hashlib
import json
import sqlite3

db = sqlite3.connect("/data/index.db")
db.row_factory = sqlite3.Row

folder_cols = (
    "id", "name", "path", "parent_id", "content_type", "root_mapping_id",
    "depth", "child_folder_count", "resource_count", "modified_at", "status",
)
resource_cols = (
    "id", "name", "path", "parent_id", "content_type", "root_mapping_id",
    "extension", "mime_type", "size", "modified_at", "thumbnail",
    "metadata_json", "status",
)

def rows(table, cols):
    selected = ", ".join(cols)
    return [
        [row[col] for col in cols]
        for row in db.execute(f"SELECT {selected} FROM {table} ORDER BY id")
    ]

payload = {
    "folders": rows("folders", folder_cols),
    "resources": rows("resources", resource_cols),
}
encoded = json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    default=str,
).encode("utf-8")
print(hashlib.sha256(encoded).hexdigest())
PY
}

running_run_info() {
  api_python <<'PY'
import sqlite3

db = sqlite3.connect("/data/state.db")
rows = db.execute(
    """
    SELECT r.id, r.root_mapping_id,
           SUM(CASE WHEN d.status = 'done' THEN 1 ELSE 0 END) AS done_count,
           SUM(CASE WHEN d.status = 'running' THEN 1 ELSE 0 END) AS running_count,
           SUM(CASE WHEN d.status = 'pending' THEN 1 ELSE 0 END) AS pending_count
    FROM index_scan_runs r
    LEFT JOIN index_scan_dirs d ON d.scan_run_id = r.id
    WHERE r.status = 'running'
    GROUP BY r.id, r.root_mapping_id, r.started_at
    ORDER BY r.started_at DESC
    """
).fetchall()
if len(rows) > 1:
    raise SystemExit(
        "multiple durable scan runs are active; refusing ambiguous restart E2E: "
        + ", ".join(str(row[0]) for row in rows)
    )
if rows:
    print("|".join(str(value or 0) for value in rows[0]))
PY
}

assert_resumed_run_complete() {
  local run_id="$1"
  api_python "$run_id" <<'PY'
import sqlite3
import sys

run_id = sys.argv[1]
db = sqlite3.connect("/data/state.db")
run = db.execute(
    "SELECT status, error_message FROM index_scan_runs WHERE id = ?",
    (run_id,),
).fetchone()
if run is None:
    raise SystemExit(f"scan run disappeared: {run_id}")
if run[0] != "completed":
    raise SystemExit(
        f"scan run did not resume to completed: id={run_id} status={run[0]} error={run[1]}"
    )

counts = dict(
    db.execute(
        """
        SELECT status, COUNT(*)
        FROM index_scan_dirs
        WHERE scan_run_id = ?
        GROUP BY status
        """,
        (run_id,),
    ).fetchall()
)
bad = {
    status: counts.get(status, 0)
    for status in ("pending", "running", "failed")
    if counts.get(status, 0)
}
if bad:
    raise SystemExit(f"unfinished durable dirs remain for {run_id}: {bad}")

done = counts.get("done", 0)
if done <= 0:
    raise SystemExit(f"resume test completed no directories: {run_id}")
print(f"resumed run completed: id={run_id} done_dirs={done}")
PY
}

echo "== Durable Scan E2E =="
echo "compose file: $COMPOSE_FILE"

compose up -d --wait api
check_durable_flag
check_durable_schema
assert_no_running_scans

echo
echo "1/5 clean scan"
run_sync
assert_no_running_scans
baseline_fingerprint="$(inventory_fingerprint)"
echo "baseline inventory: $baseline_fingerprint"

echo
echo "2/5 start a second scan and wait for an active durable run"
interrupt_log="$(mktemp)"
sync_pid=""
cleanup() {
  if [[ -n "${sync_pid:-}" ]] && kill -0 "$sync_pid" 2>/dev/null; then
    kill "$sync_pid" 2>/dev/null || true
    wait "$sync_pid" 2>/dev/null || true
  fi
  rm -f "$interrupt_log"
}
trap cleanup EXIT

(
  set +e
  run_sync >"$interrupt_log" 2>&1
) &
sync_pid=$!

run_info=""
for _ in $(seq 1 "$POLL_ATTEMPTS"); do
  if ! run_info="$(running_run_info)"; then
    wait "$sync_pid" || true
    sync_pid=""
    echo "Durable scan state became ambiguous while waiting for interruption." >&2
    echo "--- sync output ---" >&2
    cat "$interrupt_log" >&2
    exit 3
  fi
  if [[ -n "$run_info" ]]; then
    IFS='|' read -r _run_id _root_mapping_id _done_count _running_count _pending_count <<<"$run_info"
    if (( _running_count + _pending_count > 0 )); then
      break
    fi
  fi
  sleep "$POLL_SECONDS"
done

if [[ -z "$run_info" ]]; then
  wait "$sync_pid" || true
  sync_pid=""
  echo "Could not catch a running durable scan." >&2
  echo "Use a larger provider fixture/root or reduce CLOUDSITE_E2E_POLL_SECONDS." >&2
  echo "--- sync output ---" >&2
  cat "$interrupt_log" >&2
  exit 3
fi

IFS='|' read -r run_id root_mapping_id done_count running_count pending_count <<<"$run_info"
echo "caught run: id=$run_id root=$root_mapping_id done=$done_count running=$running_count pending=$pending_count"

echo
echo "3/5 interrupt by restarting API"
compose restart api
wait "$sync_pid" || true
sync_pid=""
compose up -d --wait api
check_durable_flag

echo
echo "4/5 resume"
run_sync
assert_resumed_run_complete "$run_id"
assert_no_running_scans

echo
echo "5/5 inventory equivalence"
resumed_fingerprint="$(inventory_fingerprint)"
echo "resumed inventory:  $resumed_fingerprint"

if [[ "$baseline_fingerprint" != "$resumed_fingerprint" ]]; then
  echo "FAIL: final inventory differs from the clean scan baseline." >&2
  exit 4
fi

echo
echo "PASS: durable scan resumed the interrupted run and final inventory matches clean scan."
