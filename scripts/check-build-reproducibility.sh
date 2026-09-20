#!/usr/bin/env bash
# Static checks for build reproducibility (no docker build required).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

check() {
  if [ "$1" -eq 0 ]; then
    echo "  PASS: $2"
  else
    echo "  FAIL: $2"
    fail=1
  fi
}

echo "== Web lockfile =="
web_lock="$root/apps/web/pnpm-lock.yaml"
[ -f "$web_lock" ]
check $? "pnpm-lock.yaml exists at apps/web/pnpm-lock.yaml"

grep -q -- '--frozen-lockfile' "$root/apps/web/Dockerfile"
check $? "apps/web/Dockerfile uses --frozen-lockfile"

grep -q -- '--no-frozen-lockfile' "$root/apps/web/Dockerfile" && rc=1 || rc=0
check $rc "apps/web/Dockerfile does not use --no-frozen-lockfile"

grep -q 'pnpm-lock.yaml' "$root/apps/web/Dockerfile"
check $? "apps/web/Dockerfile COPYs pnpm-lock.yaml"

echo "== API lockfile =="
api_lock="$root/apps/api/requirements.lock"
[ -f "$api_lock" ]
check $? "requirements.lock exists at apps/api/requirements.lock"

grep -q 'requirements.lock' "$root/apps/api/Dockerfile"
check $? "apps/api/Dockerfile references requirements.lock"

grep -q -- '--no-deps' "$root/apps/api/Dockerfile"
check $? "apps/api/Dockerfile installs requirements.lock with --no-deps"

echo "== API production image excludes test =="
# Extract the runner stage (last FROM ... AS runner to EOF or next FROM)
runner_stage=$(awk '/^FROM .* AS runner/{found=1} found{print}' "$root/apps/api/Dockerfile")
echo "$runner_stage" | grep -q '\.\[test\]' && rc=1 || rc=0
check $rc "runner stage does not install .[test]"

echo "$runner_stage" | grep -Eq 'COPY .*tests' && rc=1 || rc=0
check $rc "runner stage does not COPY tests directory"

echo "$runner_stage" | grep -q 'pytest' && rc=1 || rc=0
check $rc "runner stage does not reference pytest"

echo "== Summary =="
if [ "$fail" -eq 0 ]; then
  echo "All build reproducibility checks passed."
  exit 0
else
  echo "Build reproducibility checks FAILED."
  exit 1
fi
