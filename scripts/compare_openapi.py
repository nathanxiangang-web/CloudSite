#!/usr/bin/env python3
"""OpenAPI Snapshot 对比脚本：对比两个 openapi.json 的 paths/methods/schemas/status codes。

允许差异：operationId、tags、description 文本变化。
对比维度：paths、methods、request schema、response schema、status codes。
"""
import argparse
import json
import sys
from pathlib import Path

ALLOWED_DIFF_KEYS = {"operationId", "tags", "summary", "description"}


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diff_paths(before: dict, after: dict) -> list[str]:
    diffs: list[str] = []
    before_paths = set(before.get("paths", {}).keys())
    after_paths = set(after.get("paths", {}).keys())

    only_before = before_paths - after_paths
    only_after = after_paths - before_paths
    if only_before:
        diffs.append(f"[PATH] 仅 before 存在: {sorted(only_before)}")
    if only_after:
        diffs.append(f"[PATH] 仅 after 存在: {sorted(only_after)}")

    common = before_paths & after_paths
    for path in sorted(common):
        b_ops = before["paths"][path]
        a_ops = after["paths"][path]
        b_methods = set(b_ops.keys()) - {"parameters"}
        a_methods = set(a_ops.keys()) - {"parameters"}
        if b_methods != a_methods:
            diffs.append(f"[METHOD] {path}: before={sorted(b_methods)} after={sorted(a_methods)}")
            continue
        for method in sorted(b_methods & a_methods):
            b_op = b_ops[method]
            a_op = a_ops[method]
            b_keys = set(b_op.keys())
            a_keys = set(a_op.keys())
            new_keys = a_keys - b_keys
            removed_keys = b_keys - a_keys
            real_new = new_keys - ALLOWED_DIFF_KEYS
            real_removed = removed_keys - ALLOWED_DIFF_KEYS
            if real_new:
                diffs.append(f"[OP-KEY] {path} {method}: 新增字段 {sorted(real_new)}")
            if real_removed:
                diffs.append(f"[OP-KEY] {path} {method}: 删除字段 {sorted(real_removed)}")

            for key in ("requestBody", "responses"):
                if key in b_op and key in a_op:
                    b_val = json.dumps(b_op[key], sort_keys=True)
                    a_val = json.dumps(a_op[key], sort_keys=True)
                    if b_val != a_val:
                        diffs.append(f"[{key.upper()}] {path} {method}: schema 不一致")

    return diffs


def _diff_components(before: dict, after: dict, section: str) -> list[str]:
    diffs: list[str] = []
    b = before.get("components", {}).get(section, {})
    a = after.get("components", {}).get(section, {})
    b_keys = set(b.keys())
    a_keys = set(a.keys())
    only_before = b_keys - a_keys
    only_after = a_keys - b_keys
    if only_before:
        diffs.append(f"[COMPONENT-{section}] 仅 before 存在: {sorted(only_before)}")
    if only_after:
        diffs.append(f"[COMPONENT-{section}] 仅 after 存在: {sorted(only_after)}")
    for name in sorted(b_keys & a_keys):
        b_val = json.dumps(b[name], sort_keys=True)
        a_val = json.dumps(a[name], sort_keys=True)
        if b_val != a_val:
            diffs.append(f"[COMPONENT-{section}] {name}: 内容不一致")
    return diffs


def compare(before_path: str, after_path: str) -> tuple[bool, list[str]]:
    before = _load(before_path)
    after = _load(after_path)

    diffs: list[str] = []
    diffs.extend(_diff_paths(before, after))
    diffs.extend(_diff_components(before, after, "schemas"))
    diffs.extend(_diff_components(before, after, "responses"))
    diffs.extend(_diff_components(before, after, "parameters"))

    return (len(diffs) == 0, diffs)


def main():
    parser = argparse.ArgumentParser(description="对比两个 OpenAPI JSON 快照")
    parser.add_argument("--before", required=True, help="before openapi.json 路径")
    parser.add_argument("--after", required=True, help="after openapi.json 路径")
    args = parser.parse_args()

    match, diffs = compare(args.before, args.after)
    if match:
        print("MATCH: OpenAPI 快照一致（允许 operationId/tags/summary/description 差异）")
        sys.exit(0)
    else:
        print("DIFF: OpenAPI 快照存在差异")
        for d in diffs:
            print(f"  - {d}")
        sys.exit(1)


if __name__ == "__main__":
    main()