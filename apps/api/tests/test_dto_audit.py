"""1.0 Public DTO 审计测试。

验证所有公开 API 序列化函数的输出不包含敏感字段：
- password_hash / password_ciphertext
- session_token_hash / token_hash
- raw_url / sign（AList 内部签名）
- code_hash（分享码哈希）
- internal path / root_mapping_id（公开不必要时）

对应 1.0 开发文档第 17 节：Public DTO 审计。
"""
from types import SimpleNamespace
from datetime import datetime, timezone

from cloudsite.main import (
    resource_dict,
    folder_dict,
    share_dict,
    site_settings_dict,
    download_diagnostic_dict,
    sync_run_dict,
)
from cloudsite.auth import user_dict

# 公开 DTO 中绝对不应出现的字段名
SENSITIVE_FIELDS = {
    "password_hash",
    "password_ciphertext",
    "password",
    "session_token_hash",
    "token_hash",
    "raw_url",
    "sign",
    "code_hash",
    "secret_key",
    "master_key",
    "credential_key",
    "alist_password",
    "internal_path",
}


def _assert_no_sensitive_fields(payload: dict, context: str = ""):
    """递归检查字典中不包含敏感字段。"""
    for key, value in payload.items():
        assert key not in SENSITIVE_FIELDS, (
            f"DTO 审计失败{context}: 字段 '{key}' 不应出现在公开响应中"
        )
        if isinstance(value, dict):
            _assert_no_sensitive_fields(value, context)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _assert_no_sensitive_fields(item, context)


def test_resource_dict_excludes_sensitive_fields():
    """resource_dict 不泄漏内部路径、上游 URL 或存储签名。"""
    resource = SimpleNamespace(
        id="r1",
        name="tool.exe",
        parent_id="f1",
        content_type="software",
        extension="exe",
        mime_type="application/octet-stream",
        size=1024,
        modified_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        thumbnail="https://upstream/private-sign-token",
    )
    parent = SimpleNamespace(id="f1", name="工具")
    payload = resource_dict(resource, parent)
    _assert_no_sensitive_fields(payload, " (resource_dict)")
    # thumbnail 应被清空，不泄漏上游签名 URL
    assert payload["thumbnail"] == ""
    # 不包含内部路径
    assert "path" not in payload
    assert "root_mapping_id" not in payload


def test_folder_dict_excludes_internal_path_by_default():
    """folder_dict 默认不暴露内部 path 和 root_mapping_id。"""
    folder = SimpleNamespace(
        id="f1",
        name="工具",
        parent_id=None,
        content_type="software",
        depth=1,
        child_folder_count=0,
        resource_count=1,
        modified_at=None,
        path="/软件/工具",
        root_mapping_id=1,
        status="active",
        indexed_at=None,
    )
    public = folder_dict(folder)
    _assert_no_sensitive_fields(public, " (folder_dict public)")
    assert "path" not in public
    assert "root_mapping_id" not in public
    assert "status" not in public
    assert "indexed_at" not in public


def test_folder_dict_admin_includes_path_but_still_no_secrets():
    """folder_dict include_path=True（admin 用）包含 path，但仍不含敏感字段。"""
    folder = SimpleNamespace(
        id="f1",
        name="工具",
        parent_id=None,
        content_type="software",
        depth=1,
        child_folder_count=0,
        resource_count=1,
        modified_at=None,
        path="/软件/工具",
        root_mapping_id=1,
        status="active",
        indexed_at=None,
    )
    admin = folder_dict(folder, include_path=True)
    _assert_no_sensitive_fields(admin, " (folder_dict admin)")
    assert admin["path"] == "/软件/工具"


def test_share_dict_excludes_code_hash_and_internal_fields():
    """share_dict 不暴露 code_hash，只暴露 has_code 布尔值。"""
    share = SimpleNamespace(
        token="abc123",
        object_type="resource",
        object_id="r1",
        title="test.zip",
        enabled=True,
        access_mode="code",
        code_hash="sha256-hashed-code-value",
        code_version=1,
        expires_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        cancelled_at=None,
        cancel_reason=None,
        access_count=5,
        view_count=5,
        download_count=3,
        last_accessed_at=None,
        last_downloaded_at=None,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    payload = share_dict(share)
    _assert_no_sensitive_fields(payload, " (share_dict)")
    # code_hash 不应出现，只有 has_code 布尔
    assert "code_hash" not in payload
    assert "has_code" in payload
    assert payload["has_code"] is True


def test_user_dict_excludes_password_hash_and_session_tokens():
    """user_dict 不暴露 password_hash 或任何 session token。"""
    user = SimpleNamespace(
        id=1,
        username="testuser",
        status="active",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        last_login_at=None,
        password_changed_at=None,
        disabled_at=None,
        deleted_at=None,
        created_by_admin=False,
    )
    payload = user_dict(user)
    _assert_no_sensitive_fields(payload, " (user_dict)")
    assert "password_hash" not in payload
    assert "password" not in payload


def test_site_settings_dict_excludes_secrets():
    """site_settings_dict 不泄漏密钥。"""
    settings = SimpleNamespace(
        id=1,
        site_name="CloudSite",
        home_title="Welcome",
        description="A resource site",
        recent_limit=6,
        popular_limit=6,
        collection_limit=4,
        share_image_name="share.png",
        hero_subtitle="",
        footer_text="",
        submission_email="test@example.com",
        github_url="",
        registration_enabled=True,
        default_share_duration="24h",
    )
    payload = site_settings_dict(settings)
    _assert_no_sensitive_fields(payload, " (site_settings_dict)")


def test_download_diagnostic_dict_excludes_secrets():
    """download_diagnostic_dict 不泄漏 AList 凭据或签名。"""
    diag = SimpleNamespace(
        id=1,
        resource_id="r1",
        status="success",
        failed_step=None,
        error_code=None,
        message=None,
        duration_ms=150,
        target_host="alist.example",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    payload = download_diagnostic_dict(diag)
    _assert_no_sensitive_fields(payload, " (download_diagnostic_dict)")


def test_sync_run_dict_excludes_secrets():
    """sync_run_dict 不泄漏内部凭据。"""
    run = SimpleNamespace(
        id=1,
        sync_type="scheduled",
        status="success",
        folders_scanned=50,
        resources_scanned=200,
        added_count=5,
        updated_count=3,
        removed_count=0,
        started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 1, 0, 10, tzinfo=timezone.utc),
        duration_ms=600000,
        error_message=None,
        current_path="",
        roots_total=3,
        roots_completed=3,
        roots_failed=0,
    )
    payload = sync_run_dict(run)
    _assert_no_sensitive_fields(payload, " (sync_run_dict)")
