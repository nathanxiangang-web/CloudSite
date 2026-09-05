"""M0: 后台路由清单 — 从 FastAPI 实例自动盘点所有 /api/admin/** 路由。

确保没有遗漏新注册的后台接口，为 M4 路由矩阵测试提供基础。
"""
from cloudsite.main import app, users_router


def _collect_admin_routes() -> list[tuple[str, str]]:
    """从 app.routes 和已 include 的子 router 合并盘点后台路由。

    某些子 router（如 users_router）的路由可能不直接出现在 app.routes 中，
    合并子 router 确保盘点完整。
    """
    sources = [app, users_router]
    routes: list[tuple[str, str]] = []
    for source in sources:
        for route in getattr(source, "routes", []):
            if not hasattr(route, "path"):
                continue
            if not route.path.startswith("/api/admin"):
                continue
            methods = getattr(route, "methods", None) or set()
            for method in sorted(methods):
                if method in ("HEAD", "OPTIONS"):
                    continue
                routes.append((method, route.path))
    # 去重
    return sorted(set(routes))


def test_admin_route_inventory_covers_all_modules():
    routes = _collect_admin_routes()
    paths = {path for _, path in routes}
    expected_prefixes = [
        "/api/admin/auth",
        "/api/admin/alist",
        "/api/admin/sync",
        "/api/admin/root-mappings",
        "/api/admin/collections",
        "/api/admin/shares",
        "/api/admin/system",
        "/api/admin/site",
        "/api/admin/submissions",
        "/api/admin/notifications",
        "/api/admin/identities",
        "/api/admin/users",
    ]
    missing = [prefix for prefix in expected_prefixes if not any(p.startswith(prefix) for p in paths)]
    assert not missing, f"缺少后台路由前缀: {missing}"
    assert len(routes) >= 30, f"后台路由数量过少: {len(routes)}"


def test_admin_route_inventory_includes_dynamic_paths():
    routes = _collect_admin_routes()
    paths = {path for _, path in routes}
    assert any("{" in p for p in paths), "未发现动态路径路由"


def test_admin_route_inventory_snapshot():
    """打印当前路由清单，便于审查。"""
    routes = _collect_admin_routes()
    assert len(routes) > 0
