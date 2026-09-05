"""M1: admin_auth 纯函数测试 — 验证精确白名单和三态模型。

不依赖数据库或 HTTP，纯策略逻辑测试。
"""
from cloudsite.admin_auth import (
    AdminAuthMode,
    is_admin_path,
    is_public_admin_endpoint,
    resolve_admin_auth_mode,
    should_block_admin_request,
)


def test_public_endpoints_are_precise():
    assert is_public_admin_endpoint("GET", "/api/admin/auth/status")
    assert is_public_admin_endpoint("POST", "/api/admin/auth/login")
    assert is_public_admin_endpoint("POST", "/api/admin/auth/logout")
    assert is_public_admin_endpoint("GET", "/api/admin/setup/status")
    assert is_public_admin_endpoint("POST", "/api/admin/setup/alist")


def test_unknown_auth_path_not_public():
    """/api/admin/auth/anything 不公开（修复前缀放行漏洞）。"""
    assert not is_public_admin_endpoint("GET", "/api/admin/auth/anything")
    assert not is_public_admin_endpoint("POST", "/api/admin/auth/debug")
    assert not is_public_admin_endpoint("GET", "/api/admin/auth/")


def test_method_distinction():
    """同路径不同方法能区分。"""
    assert is_public_admin_endpoint("GET", "/api/admin/auth/status")
    assert not is_public_admin_endpoint("POST", "/api/admin/auth/status")


def test_business_endpoints_not_public():
    assert not is_public_admin_endpoint("GET", "/api/admin/alist")
    assert not is_public_admin_endpoint("GET", "/api/admin/system")
    assert not is_public_admin_endpoint("GET", "/api/admin/collections")
    assert not is_public_admin_endpoint("POST", "/api/admin/collections")
    assert not is_public_admin_endpoint("DELETE", "/api/admin/submissions/1")


def test_resolve_mode_setup_required():
    assert resolve_admin_auth_mode(setup_completed=False, admin_cookie_valid=False) == AdminAuthMode.SETUP_REQUIRED
    assert resolve_admin_auth_mode(setup_completed=False, admin_cookie_valid=True) == AdminAuthMode.SETUP_REQUIRED


def test_resolve_mode_login_required():
    assert resolve_admin_auth_mode(setup_completed=True, admin_cookie_valid=False) == AdminAuthMode.LOGIN_REQUIRED


def test_resolve_mode_authenticated():
    assert resolve_admin_auth_mode(setup_completed=True, admin_cookie_valid=True) == AdminAuthMode.AUTHENTICATED


def test_should_block_setup_required():
    block, code = should_block_admin_request(method="GET", path="/api/admin/system", setup_completed=False, admin_cookie_valid=False)
    assert block and code == "SETUP_REQUIRED"


def test_should_block_login_required():
    block, code = should_block_admin_request(method="GET", path="/api/admin/system", setup_completed=True, admin_cookie_valid=False)
    assert block and code == "ADMIN_REQUIRED"


def test_should_allow_authenticated():
    block, code = should_block_admin_request(method="GET", path="/api/admin/system", setup_completed=True, admin_cookie_valid=True)
    assert not block and code is None


def test_should_allow_public_endpoint_even_when_setup_required():
    block, code = should_block_admin_request(method="GET", path="/api/admin/auth/status", setup_completed=False, admin_cookie_valid=False)
    assert not block and code is None


def test_should_allow_options():
    block, code = should_block_admin_request(method="OPTIONS", path="/api/admin/system", setup_completed=False, admin_cookie_valid=False)
    assert not block and code is None


def test_should_allow_non_admin_path():
    block, code = should_block_admin_request(method="GET", path="/api/health", setup_completed=False, admin_cookie_valid=False)
    assert not block and code is None


def test_alist_enabled_not_in_policy():
    """策略函数不接受 alist_enabled 参数，AList 状态不参与认证判定。"""
    block, _ = should_block_admin_request(method="GET", path="/api/admin/system", setup_completed=True, admin_cookie_valid=False)
    assert block


def test_is_admin_path():
    assert is_admin_path("/api/admin/system")
    assert is_admin_path("/api/admin/submissions/1")
    assert not is_admin_path("/api/health")
    assert not is_admin_path("/api/auth/login")
