#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

module_probe="apps/api/cloudsite/modules/catalog/application/__architecture_debt_probe__.py"
cross_probe="apps/api/cloudsite/modules/catalog/application/__architecture_cross_probe__.py"
router_probe="apps/api/cloudsite/routers/__architecture_debt_probe__.py"
baseline_file="docs/development/architecture-debt-baseline.json"
baseline_backup="$(mktemp)"

cp "$baseline_file" "$baseline_backup"

cleanup() {
  rm -f "$module_probe" "$cross_probe" "$router_probe"
  if [[ -f "$baseline_backup" ]]; then
    cp "$baseline_backup" "$baseline_file"
    rm -f "$baseline_backup"
  fi
}
trap cleanup EXIT

cat >"$module_probe" <<'PY'
from cloudsite.models import Resource
PY

cat >"$cross_probe" <<'PY'
from cloudsite.modules.users.application import service
PY

cat >"$router_probe" <<'PY'
from sqlalchemy import select
PY

set +e
output="$(python scripts/check-architecture-debt.py --baseline-ref HEAD 2>&1)"
status=$?
set -e
printf '%s\n' "$output"

if [[ "$status" -eq 0 ]]; then
  echo "architecture debt self-test FAILED: scanner accepted deliberate new debt" >&2
  exit 1
fi

expected_ids=(
  "module_legacy_import::apps/api/cloudsite/modules/catalog/application/__architecture_debt_probe__.py::cloudsite.models"
  "cross_module_internal_import::apps/api/cloudsite/modules/catalog/application/__architecture_cross_probe__.py::cloudsite.modules.users.application"
  "router_orm_import::apps/api/cloudsite/routers/__architecture_debt_probe__.py::sqlalchemy"
)

for debt_id in "${expected_ids[@]}"; do
  if ! grep -Fq "$debt_id" <<<"$output"; then
    echo "architecture debt self-test FAILED: missing expected debt ID: $debt_id" >&2
    exit 1
  fi
done

rm -f "$module_probe" "$cross_probe" "$router_probe"

# Simulate stale debt remaining in the committed baseline after code has removed it.
python - "$baseline_file" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

fake_id = "router_orm_import::apps/api/cloudsite/routers/__removed_debt_probe__.py::sqlalchemy"
payload["violations"].append(
    {
        "rule": "router_orm_import",
        "file": "apps/api/cloudsite/routers/__removed_debt_probe__.py",
        "target": "sqlalchemy",
        "id": fake_id,
    }
)
payload["counts"]["router_orm_import"] += 1

with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY

set +e
stale_output="$(python scripts/check-architecture-debt.py --baseline-ref HEAD 2>&1)"
stale_status=$?
set -e
printf '%s\n' "$stale_output"

if [[ "$stale_status" -eq 0 ]]; then
  echo "architecture debt self-test FAILED: stale baseline entry was accepted" >&2
  exit 1
fi

if ! grep -Fq "ARCHITECTURE DEBT BASELINE IS OUT OF SYNC" <<<"$stale_output"; then
  echo "architecture debt self-test FAILED: stale baseline was not reported as out of sync" >&2
  exit 1
fi

if ! grep -Fq "__removed_debt_probe__" <<<"$stale_output"; then
  echo "architecture debt self-test FAILED: stale debt ID was not reported" >&2
  exit 1
fi

cp "$baseline_backup" "$baseline_file"

python scripts/check-architecture-debt.py --baseline-ref HEAD
echo "architecture debt self-test PASSED"
