"""Pytest 全局配置：为测试环境设置固定密钥 + 测试间清空进程级缓存。

避免 validate_production_secrets 拒绝启动，并使 secret_leak 测试的
`secret_key not in body` 断言有意义（非空密钥）。
每个测试前后清空首页缓存，避免跨测试污染（CACHE-001 测试隔离）。
"""
import pytest

from cloudsite.config import settings

_TEST_SECRET = "test-only-secret-key-for-pytest-not-for-production-32chars"
settings.secret_key = _TEST_SECRET
settings.master_key = ""
settings.allow_insecure_dev_key = True


@pytest.fixture(autouse=True)
def _isolate_process_caches():
    """每个测试前后清空进程级缓存，避免跨测试数据污染。"""
    try:
        from cloudsite import main
        main._home_cache["data"] = None
        main._home_cache["fetched_at"] = 0.0
        if hasattr(main, "_storage_infos_cache"):
            main._storage_infos_cache["data"] = None
            main._storage_infos_cache["fetched_at"] = 0.0
        if hasattr(main, "_alist_connection_cache"):
            main._alist_connection_cache["data"] = None
            main._alist_connection_cache["fetched_at"] = 0.0
    except Exception:
        pass
    yield
    try:
        from cloudsite import main
        main._home_cache["data"] = None
        main._home_cache["fetched_at"] = 0.0
        if hasattr(main, "_storage_infos_cache"):
            main._storage_infos_cache["data"] = None
            main._storage_infos_cache["fetched_at"] = 0.0
        if hasattr(main, "_alist_connection_cache"):
            main._alist_connection_cache["data"] = None
            main._alist_connection_cache["fetched_at"] = 0.0
    except Exception:
        pass
