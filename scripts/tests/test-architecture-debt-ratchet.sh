#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

module_probe="apps/api/cloudsite/modules/catalog/application/__architecture_debt_probe__.py"
cross_probe="apps/api/cloudsite/modules/catalog/application/__architecture_cross_probe__.py"
router_probe="apps/api/cloudsite/routers/__architecture_debt_probe__.py"

cleanup() {
  rm -f "$module_probe" "$cross_probe" "$router_probe"
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

cleanup
trap - EXIT

python scripts/check-architecture-debt.py --baseline-ref HEAD
echo "architecture debt self-test PASSED"
