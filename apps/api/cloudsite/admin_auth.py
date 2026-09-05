"""SEC-001 统一后台认证策略（纯函数，不改变线上行为）。

M1 阶段只定义策略和数据结构，不接入中间件。
后续 M4 将用本模块替换 admin_session_middleware 中的条件判定。
"""
from __future__ import annotations

# 精确公开端点白名单：(HTTP 方法, 精确路径)
PUBLIC_ADMIN_ENDPOINTS: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/api/admin/auth/status"),
    ("POST", "/api/admin/auth/login"),
    ("POST", "/api/admin/auth/logout"),
    ("GET", "/api/admin/setup/status"),
    ("POST", "/api/admin/setup/alist"),
})


class AdminAuthMode:
    """后台认证三态。"""
    SETUP_REQUIRED = "setup_required"
    LOGIN_REQUIRED = "login_required"
    AUTHENTICATED = "authenticated"


def is_admin_path(path: str) -> bool:
    """判断是否为后台路径。"""
    return path.startswith("/api/admin")


def is_public_admin_endpoint(method: str, path: str) -> bool:
    """判断 (method, path) 是否为精确公开端点。"""
    return (method.upper(), path) in PUBLIC_ADMIN_ENDPOINTS


def resolve_admin_auth_mode(*, setup_completed: bool, admin_cookie_valid: bool) -> str:
    """根据初始化状态和 Cookie 有效性返回认证模式。

    AList enabled 状态不参与判定。
    """
    if not setup_completed:
        return AdminAuthMode.SETUP_REQUIRED
    if not admin_cookie_valid:
        return AdminAuthMode.LOGIN_REQUIRED
    return AdminAuthMode.AUTHENTICATED


def should_block_admin_request(
    *,
    method: str,
    path: str,
    setup_completed: bool,
    admin_cookie_valid: bool,
) -> tuple[bool, str | None]:
    """统一判定后台请求是否应被拦截。

    返回 (block, error_code)：
    - (False, None) 放行
    - (True, "SETUP_REQUIRED") 尚未初始化
    - (True, "ADMIN_REQUIRED") 需要管理员登录
    """
    if not is_admin_path(path):
        return (False, None)
    if method.upper() == "OPTIONS":
        return (False, None)
    if is_public_admin_endpoint(method, path):
        return (False, None)
    mode = resolve_admin_auth_mode(
        setup_completed=setup_completed,
        admin_cookie_valid=admin_cookie_valid,
    )
    if mode == AdminAuthMode.SETUP_REQUIRED:
        return (True, "SETUP_REQUIRED")
    if mode == AdminAuthMode.LOGIN_REQUIRED:
        return (True, "ADMIN_REQUIRED")
    return (False, None)


# ---- M2: 初始化状态读取与旧站兼容 ----

import hmac


def verify_setup_token(provided: str, expected: str) -> bool:
    """恒定时间比较初始化令牌。空令牌永远返回 False。"""
    if not expected:
        return False
    return hmac.compare_digest(provided or "", expected)


async def get_setup_completed(session) -> bool:
    """读取 setup_completed 标记。"""
    from .models import SystemSetting
    row = await session.get(SystemSetting, "setup_completed")
    return row is not None and (row.value or "").lower() == "true"


async def ensure_setup_compatible(session) -> None:
    """旧站兼容：有 AList 配置但无 setup_completed 标记时，自动标记为已完成。

    幂等：已有标记或无 AList 配置时不写。
    """
    from .models import AListConnection, SystemSetting
    row = await session.get(SystemSetting, "setup_completed")
    if row is not None:
        return
    connection = await session.get(AListConnection, 1)
    if connection is not None:
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await session.commit()
