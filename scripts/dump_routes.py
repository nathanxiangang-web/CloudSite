#!/usr/bin/env python3
"""Route Inventory 导出脚本：遍历 app.routes 提取 METHOD PATH NAME，按 METHOD PATH 排序输出。

用于后端拆分前后的路由清单对比，确保拆分不改变 API 契约。
"""
import argparse
import sys
from pathlib import Path


def _ensure_import_path():
    api_dir = Path(__file__).resolve().parent.parent / "apps" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))


def dump_routes(output_path: str | None = None) -> str:
    _ensure_import_path()
    from fastapi.routing import APIRoute
    from cloudsite.main import app

    def _iter_api_routes():
        for route in app.routes:
            if isinstance(route, APIRoute):
                yield route
                continue
            # FastAPI >=0.115 wraps included routers in _IncludedRouter
            original = getattr(route, "original_router", None)
            if original is not None:
                for sub in getattr(original, "routes", []):
                    if isinstance(sub, APIRoute):
                        yield sub

    rows: list[tuple[str, str, str]] = []
    for route in _iter_api_routes():
        methods = sorted(route.methods) if route.methods else ["UNKNOWN"]
        for method in methods:
            rows.append((method, route.path, route.name or ""))

    rows.sort(key=lambda r: (r[0], r[1]))
    lines = [f"{m} {p} {n}" for m, p, n in rows]
    text = "\n".join(lines) + "\n"

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text, encoding="utf-8")

    return text


def main():
    parser = argparse.ArgumentParser(description="导出 FastAPI Route Inventory")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径")
    args = parser.parse_args()

    text = dump_routes(args.output)
    if not args.output:
        print(text, end="")
    count = text.count("\n")
    print(f"# 共 {count} 条路由", file=sys.stderr)
    if args.output:
        print(f"# 已写入 {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()