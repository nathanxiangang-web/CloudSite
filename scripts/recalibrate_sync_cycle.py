#!/usr/bin/env python3
"""Recalibrate a CloudSite sync cycle after the empty-directory compatibility fix.

One-time remediation for the v0.3.4 sync fix. It:

1. Resets failed sync_cycle_items whose error is the empty-directory content bug
   ("目录响应缺少完整 content 列表") back to ``pending`` (attempts cleared) so they
   re-scan cleanly with the fixed AList client.
2. Recalibrates the cycle's ``planned_folder_count`` against the real queue size.
3. Zeroes the inflated cumulative ``alist_list_requests`` counter.

Run with the CloudSite API stopped (no active WAL writer), e.g.:

    python3 scripts/recalibrate_sync_cycle.py ./data

The script is idempotent: after a successful re-scan no items match the empty-content
error, so re-running it is a no-op.
"""

import argparse
import sqlite3
from pathlib import Path

EMPTY_CONTENT_MARKER = "缺少完整 content"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", nargs="?", default="./data", help="数据目录（包含 index.db）")
    args = parser.parse_args()

    index_path = Path(args.data_dir) / "index.db"
    if not index_path.exists():
        print(f"未找到 {index_path}")
        return 1

    conn = sqlite3.connect(index_path)
    try:
        row = conn.execute("SELECT id FROM sync_cycles ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            print("没有找到 sync_cycles 记录")
            return 1
        cycle_id = row[0]

        reset = conn.execute(
            "UPDATE sync_cycle_items "
            "SET status='pending', attempts=0, error_message='' "
            "WHERE cycle_id=? AND status='failed' AND error_message LIKE ?",
            (cycle_id, f"%{EMPTY_CONTENT_MARKER}%"),
        ).rowcount

        planned = conn.execute(
            "SELECT COUNT(*) FROM sync_cycle_items WHERE cycle_id=?", (cycle_id,)
        ).fetchone()[0]

        conn.execute(
            "UPDATE sync_cycles "
            "SET planned_folder_count=?, alist_list_requests=0, "
            "failed_folder_count=0, carry_over_count=0 "
            "WHERE id=?",
            (planned, cycle_id),
        )
        conn.commit()

        print(f"Cycle #{cycle_id}")
        print(f"  重置失败项为 pending: {reset}")
        print(f"  计划目录数重算为: {planned}")
        print("  alist_list_requests 已清零")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
