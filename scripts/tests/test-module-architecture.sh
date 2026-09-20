#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

resources_manifest="apps/api/cloudsite/modules/resources/module.yaml"
providers_manifest="apps/api/cloudsite/modules/providers/module.yaml"
probe="apps/api/cloudsite/modules/providers/application/__module_architecture_probe__.py"
resources_backup="$(mktemp)"
providers_backup="$(mktemp)"

cp "$resources_manifest" "$resources_backup"
cp "$providers_manifest" "$providers_backup"

cleanup() {
  rm -f "$probe"
  if [[ -f "$resources_backup" ]]; then
    cp "$resources_backup" "$resources_manifest"
    rm -f "$resources_backup"
  fi
  if [[ -f "$providers_backup" ]]; then
    cp "$providers_backup" "$providers_manifest"
    rm -f "$providers_backup"
  fi
}
trap cleanup EXIT

python scripts/check-module-architecture.py

cat >"$probe" <<'PY'
from cloudsite.modules.catalog.contracts.public import CatalogReader
PY

python - "$resources_manifest" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
needle = "owned_tables:\n"
if needle not in text:
    raise SystemExit("owned_tables marker missing")
text = text.replace(needle, needle + '  - "catalog_entries"\n', 1)
open(path, "w", encoding="utf-8").write(text)
PY

set +e
output="$(python scripts/check-module-architecture.py 2>&1)"
status=$?
set -e
printf '%s\n' "$output"

if [[ "$status" -eq 0 ]]; then
  echo "module architecture self-test FAILED: invalid ownership/imports were accepted" >&2
  exit 1
fi

if ! grep -Fq "multiple owners" <<<"$output"; then
  echo "module architecture self-test FAILED: duplicate table ownership was not rejected" >&2
  exit 1
fi

if ! grep -Fq "does not allow 'modules/catalog/contracts'" <<<"$output"; then
  echo "module architecture self-test FAILED: undeclared contract dependency was not rejected" >&2
  exit 1
fi

rm -f "$probe"
cp "$resources_backup" "$resources_manifest"

python - "$providers_manifest" <<'PY'
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
needle = "allowed_dependencies:\n"
if needle not in text:
    raise SystemExit("allowed_dependencies marker missing")
text = text.replace(needle, needle + '  - "modules/catalog/contracts"\n', 1)
open(path, "w", encoding="utf-8").write(text)
PY

set +e
cycle_output="$(python scripts/check-module-architecture.py 2>&1)"
cycle_status=$?
set -e
printf '%s\n' "$cycle_output"

if [[ "$cycle_status" -eq 0 ]]; then
  echo "module architecture self-test FAILED: dependency cycle was accepted" >&2
  exit 1
fi

if ! grep -Fq "business module dependency cycle" <<<"$cycle_output"; then
  echo "module architecture self-test FAILED: dependency cycle was not reported" >&2
  exit 1
fi

cp "$providers_backup" "$providers_manifest"

python scripts/check-module-architecture.py
echo "module architecture self-test PASSED"
