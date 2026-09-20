#!/usr/bin/env bash
# CloudSite release version gate focused test.
# Proves a stale CLOUDSITE_IMAGE_TAG in docs/contracts.md makes
# scripts/check-release-version.py exit non-zero, and that the
# committed contracts doc keeps the checker consistent.
set -euo pipefail

FAIL=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; FAIL=1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECKER="$ROOT/scripts/check-release-version.py"
CONTRACTS="$ROOT/docs/contracts.md"
BACKUP=""

restore() {
  if [[ -n "$BACKUP" && -f "$BACKUP" ]]; then
    cp "$BACKUP" "$CONTRACTS"
    rm -f "$BACKUP"
  fi
}
trap restore EXIT

# 1. Baseline: checker passes with the committed contracts doc.
if python3 "$CHECKER" >/dev/null 2>&1; then
  pass "checker passes with current contracts doc"
else
  fail "checker should pass with current contracts doc"
fi

# 2. Negative: a stale contracts-doc tag must make the checker fail.
BACKUP="$(mktemp "${TMPDIR:-/tmp}/contracts.XXXXXX")"
cp "$CONTRACTS" "$BACKUP"
python3 - "$CONTRACTS" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
needle = "| `CLOUDSITE_IMAGE_TAG` | `v1.0.0` |"
replacement = "| `CLOUDSITE_IMAGE_TAG` | `v1.0.0-beta.3` |"
if needle not in t:
    raise SystemExit("anchor line not found: " + needle)
p.write_text(t.replace(needle, replacement, 1), encoding="utf-8")
PY

if python3 "$CHECKER" >/dev/null 2>&1; then
  fail "checker should fail with stale contracts-doc tag"
else
  pass "checker fails with stale contracts-doc tag"
fi

exit "$FAIL"
