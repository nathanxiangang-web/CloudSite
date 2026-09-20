#!/usr/bin/env python3
"""Reset CloudSite demo data to a clean seeded state.

Clears catalog entries, collections, collection items, quality todos,
AI drafts, and search query logs, then re-seeds default collections
and resets the seed flag so the application re-seeds on next start.

Usage:
    python3 scripts/reset_demo_data.py ./data

Run with the CloudSite API stopped (no active WAL writer).
The script is safe to re-run: it always clears then re-seeds.
"""
import argparse
import sqlite3
import sys
from pathlib import Path


TABLES_TO_CLEAR = [
    "collection_items",
    "collections",
    "catalog_entries",
    "catalog_versions",
    "catalog_assets",
    "quality_todos",
    "quality_detection_runs",
    "search_query_logs",
    "content_feedback",
    "ai_generation_drafts",
    "ai_budget_usage",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", nargs="?", default="./data", help="数据目录（包含 state.db）")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    state_db = data_dir / "state.db"

    if not state_db.exists():
        print(f"Error: {state_db} not found", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(state_db))
    try:
        cur = conn.cursor()

        for table in TABLES_TO_CLEAR:
            cur.execute(f"DELETE FROM {table}")
            print(f"  cleared {table}: {cur.rowcount} rows")

        cur.execute(
            "DELETE FROM system_settings WHERE key = 'default_collections_seeded'"
        )
        print(f"  reset seed flag: {cur.rowcount} rows")

        conn.commit()
        print("\nDemo data reset complete. Start the API to re-seed default collections.")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())