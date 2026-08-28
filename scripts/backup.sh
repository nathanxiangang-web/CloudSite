#!/usr/bin/env bash
# CloudSite 备份：打包 data/（state.db + index.db）与 .env。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$ROOT/cloudsite-backup-$STAMP.tar.gz}"
tar -czf "$OUT" -C "$ROOT" data .env
echo "备份完成：$OUT"
