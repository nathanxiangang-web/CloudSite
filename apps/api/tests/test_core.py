import pytest
from types import SimpleNamespace

from cloudsite import main
from cloudsite.alist import AListClient, AListError, AListUrlBuilder
from cloudsite.crypto import decrypt_secret, encrypt_secret
from cloudsite.download import DownloadError, DownloadUrlCache, map_alist_error, validate_download_url, validate_resource_id
from cloudsite.indexer import join_path, normalize_path, preserve_existing_ids, scan_roots, should_ignore, stable_id, times_equal
from cloudsite.main import breadcrumbs_for, create_session_token, folder_dict, resource_dict, verify_session_token
from cloudsite.search import build_fts_query, classify_match, escape_like, normalize_search_query
from cloudsite.preview import preview_capability, validate_download_url


def test_stable_ids_are_deterministic():
    assert stable_id("resource", "/Apps/test.zip") == stable_id("resource", "/Apps/test.zip")
    assert stable_id("resource", "/Apps/test.zip") != stable_id("folder", "/Apps/test.zip")
    assert stable_id("resource", "/Apps/test.zip").startswith("r_")
    assert stable_id("folder", "/Apps").startswith("f_")


def test_join_path_normalizes_slashes():
    assert join_path("/Apps/", "Tools") == "/Apps/Tools"


def test_path_normalization_and_ignore_rule():
    assert normalize_path(" //软件///装机工具/ ") == "/软件/装机工具"
    assert normalize_path("\\Docs\\Manuals") == "/Docs/Manuals"
    assert should_ignore("/.cloudsite/settings.json") is True
    assert should_ignore("/软件/.cloudsite/cache") is True
    assert should_ignore("/软件/cloudsite.txt") is False


def test_index_time_comparison_normalizes_sqlite_timezone():
    from datetime import datetime, timezone

    assert times_equal(datetime(2026, 8, 28, 0, 0), datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc))


def test_public_serializers_do_not_leak_storage_paths_or_upstream_urls():
    folder = SimpleNamespace(id="f1", name="工具", path="/软件/工具", parent_id=None, content_type="software", root_mapping_id=1, depth=1, child_folder_count=0, resource_count=1, modified_at=None, status="active", indexed_at=None)
    resource = SimpleNamespace(id="r1", name="tool.exe", path="/软件/工具/tool.exe", parent_id="f1", content_type="software", root_mapping_id=1, extension="exe", mime_type="application/octet-stream", size=10, modified_at=None, thumbnail="https://upstream/private-thumbnail")
    public_folder = folder_dict(folder)
    public_resource = resource_dict(resource, folder)
    assert "path" not in public_folder
    assert "root_mapping_id" not in public_folder
    assert "path" not in public_resource
    assert "root_mapping_id" not in public_resource
    assert public_resource["thumbnail"] == ""
    assert public_resource["parent"] == {"id": "f1", "name": "工具"}
    assert folder_dict(folder, include_path=True)["path"] == "/软件/工具"


def test_public_breadcrumbs_use_ids_and_names_only():
    root = SimpleNamespace(id="root", name="软件", parent_id=None)
    child = SimpleNamespace(id="child", name="工具", parent_id="root")
    assert breadcrumbs_for(child, {"root": root, "child": child}) == [
        {"id": "root", "name": "软件"},
        {"id": "child", "name": "工具"},
    ]


def test_admin_session_token_rejects_tampering():
    token = create_session_token("admin")
    assert verify_session_token(token) is True
    assert verify_session_token(f"{token}tampered") is False


def test_admin_session_token_rejects_expiry(monkeypatch):
    monkeypatch.setattr(main.time, "time", lambda: 1_000)
    token = create_session_token("admin")
    monkeypatch.setattr(main.time, "time", lambda: 1_000 + 86400 * 8)
    assert verify_session_token(token) is False


def test_secret_encryption_roundtrip_hides_plaintext():
    plaintext = "m1-test-password"
    ciphertext = encrypt_secret(plaintext)
    assert plaintext not in ciphertext
    assert decrypt_secret(ciphertext) == plaintext


def test_alist_rejects_invalid_base_url():
    with pytest.raises(AListError) as raised:
        AListClient("alist.local:5244", "admin", "password")
    assert raised.value.code == "AL-001"


async def test_alist_directory_filtering(monkeypatch):
    client = AListClient("http://alist.test", "admin", "password")

    async def fake_list_path(_: AListClient, __: str):
        return [
            {"name": "图片", "is_dir": True},
            {"name": "readme.txt", "is_dir": False},
            {"name": "软件", "is_dir": True},
        ]

    monkeypatch.setattr(AListClient, "list_path", fake_list_path)
    directories = await client.list_directories("/")
    assert [item["name"] for item in directories] == ["图片", "软件"]


async def test_alist_test_verifies_root_access(monkeypatch):
    client = AListClient("http://alist.test", "admin", "password")
    calls = {"login": 0, "base_path": 0, "list": 0}

    async def fake_login(self):
        calls["login"] += 1
        self.token = "token"

    async def fake_list(self, _: str):
        calls["list"] += 1
        return [{"name": "软件"}, {"name": "图片"}]

    async def fake_base_path(self):
        calls["base_path"] += 1
        return "/"

    monkeypatch.setattr(AListClient, "login", fake_login)
    monkeypatch.setattr(AListClient, "list_path", fake_list)
    monkeypatch.setattr(AListClient, "get_base_path", fake_base_path)
    result = await client.test()
    assert result["item_count"] == 2
    assert result["base_path"] == "/"
    assert calls == {"login": 1, "base_path": 1, "list": 1}


async def test_alist_reauthenticates_once_when_token_expires(monkeypatch):
    client = AListClient("http://alist.test", "admin", "password", token="expired")
    calls = {"login": 0, "request": 0}

    async def fake_login(self):
        calls["login"] += 1
        self.token = "fresh"

    async def fake_request(self, method: str, path: str, **kwargs):
        calls["request"] += 1
        if calls["request"] == 1:
            raise AListError("expired", "AL-004", status_code=401, auth_failed=True)
        return {"code": 200, "data": {"content": []}}

    monkeypatch.setattr(AListClient, "login", fake_login)
    monkeypatch.setattr(AListClient, "_request", fake_request)
    assert await client.list_path("/") == []
    assert calls == {"login": 1, "request": 2}


async def test_alist_normalized_file_info_and_download_url(monkeypatch):
    client = AListClient("http://alist.test", "admin", "password")

    async def fake_get_path(self, _: str):
        return {
            "name": "manual.pdf",
            "is_dir": False,
            "size": 128,
            "modified": "2026-08-28T00:00:00Z",
            "raw_url": "http://alist.test/d/manual.pdf",
        }

    monkeypatch.setattr(AListClient, "get_path", fake_get_path)
    info = await client.get_file_info("/文档/manual.pdf")
    assert info == {
        "name": "manual.pdf",
        "is_dir": False,
        "size": 128,
        "modified": "2026-08-28T00:00:00Z",
        "path": "/文档/manual.pdf",
    }
    assert await client.get_download_url("/文档/manual.pdf") == "http://alist.test/d/manual.pdf"


async def test_alist_download_entry_uses_current_user_base_path(monkeypatch):
    client = AListClient("https://alist.test", "admin", "password")

    async def fake_get_path(self, _: str):
        return {"is_dir": False, "sign": "signed:1"}

    async def fake_base_path(self):
        return "/网盘/资源"

    monkeypatch.setattr(AListClient, "get_path", fake_get_path)
    monkeypatch.setattr(AListClient, "get_base_path", fake_base_path)
    entry = await client.get_download_entry("/软件/工具.exe")
    assert entry.url == "https://alist.test/d/%E7%BD%91%E7%9B%98/%E8%B5%84%E6%BA%90/%E8%BD%AF%E4%BB%B6/%E5%B7%A5%E5%85%B7.exe?sign=signed%3A1"


async def test_alist_preview_entry_reuses_native_entry(monkeypatch):
    client = AListClient("https://alist.test", "admin", "password")

    async def fake_download_entry(self, path):
        return AListUrlBuilder("https://alist.test", "/").build_download_entry(path, "current-sign")

    monkeypatch.setattr(AListClient, "get_download_entry", fake_download_entry)
    entry = await client.get_preview_entry("/图片/预览图.jpg")
    assert entry.url == "https://alist.test/d/%E5%9B%BE%E7%89%87/%E9%A2%84%E8%A7%88%E5%9B%BE.jpg?sign=current-sign"


async def test_dynamic_scanner_builds_deep_tree_and_ignores_metadata():
    tree = {
        "/软件": [{"name": "装机工具", "is_dir": True}, {"name": ".cloudsite", "is_dir": True}],
        "/软件/装机工具": [{"name": "浏览器", "is_dir": True}],
        "/软件/装机工具/浏览器": [{"name": "Chrome.exe", "is_dir": False, "size": 2048, "modified": "2026-08-28T00:00:00Z"}],
    }

    class FakeClient:
        async def list_path(self, path: str):
            return tree.get(path, [])

    root = SimpleNamespace(id=7, alist_path="/软件/", display_name="软件", content_type="software")
    folders, resources = await scan_roots(FakeClient(), [root])
    assert {item.path for item in folders.values()} == {"/软件", "/软件/装机工具", "/软件/装机工具/浏览器"}
    assert {item.path for item in resources.values()} == {"/软件/装机工具/浏览器/Chrome.exe"}
    browser = next(item for item in folders.values() if item.name == "浏览器")
    assert browser.depth == 2
    assert browser.resource_count == 1
    resource = next(iter(resources.values()))
    assert resource.root_mapping_id == 7
    assert resource.content_type == "software"

    legacy_folder = SimpleNamespace(id="legacy-folder-id", path="/软件/装机工具/浏览器")
    legacy_resource = SimpleNamespace(id="legacy-resource-id", path="/软件/装机工具/浏览器/Chrome.exe")
    folders, resources = preserve_existing_ids(
        folders,
        resources,
        {legacy_folder.id: legacy_folder},
        {legacy_resource.id: legacy_resource},
    )
    assert "legacy-folder-id" in folders
    assert "legacy-resource-id" in resources
    assert resources["legacy-resource-id"].parent_id == "legacy-folder-id"


async def test_dynamic_scanner_propagates_upstream_failure_without_partial_diff():
    class BrokenClient:
        async def list_path(self, path: str):
            raise AListError("temporary unavailable", "AL-002")

    root = SimpleNamespace(id=1, alist_path="/Apps", display_name="Apps", content_type="software")
    with pytest.raises(AListError):
        await scan_roots(BrokenClient(), [root])


def test_search_query_normalization_and_length_input_are_deterministic():
    assert normalize_search_query("  Google   Chrome \n") == "Google Chrome"
    assert normalize_search_query("  运维  资料 ") == "运维 资料"


def test_search_like_escaping_handles_sql_wildcards_and_backslashes():
    assert escape_like(r"100%_C:\Tools") == r"100\%\_C:\\Tools"


def test_search_fts_builder_treats_operators_and_injection_as_plain_tokens():
    assert build_fts_query("Chrome + 23H2") == '"Chrome"* AND "23H2"*'
    malicious = build_fts_query("' OR 1=1 --")
    assert malicious == '"OR"* AND "1"* AND "1"*'
    assert "--" not in malicious


def test_search_special_characters_never_create_invalid_fts_expression():
    for query in ["+", "-", "_", "()", "[]", ".", "&", "#", "中文 空格"]:
        expression = build_fts_query(query)
        assert expression == "" or all(part.startswith('"') and part.endswith('"*') for part in expression.split(" AND "))


def test_search_match_priority_is_exact_then_prefix_then_name_then_metadata():
    assert classify_match("Chrome", "chrome") == "exact"
    assert classify_match("Chrome Portable", "Chrome") == "prefix"
    assert classify_match("Google Chrome", "Chrome") == "name"
    assert classify_match("Browser", "Chrome") == "metadata"


def test_download_gateway_accepts_only_safe_resource_ids():
    assert validate_resource_id("r_a81d82fd8a9018ad") is True
    assert validate_resource_id("legacy-id_123") is True
    assert validate_resource_id("../../etc/passwd") is False
    assert validate_resource_id("") is False


def test_download_redirect_url_requires_http_host_and_no_userinfo():
    assert validate_download_url("https://cdn.example.com/file.zip?signature=secret")[1] == "cdn.example.com"
    for value in ["file:///etc/passwd", "ftp://example.com/file", "javascript:alert(1)", "https:///missing-host", "https://user:pass@example.com/file"]:
        with pytest.raises(DownloadError) as raised:
            validate_download_url(value)
        assert raised.value.code == "DL-008"


def test_alist_native_download_entry_preserves_base_path_and_encodes_each_path_segment():
    entry = AListUrlBuilder("https://alist.example.com/cloudsite", "/软件").build_download_entry(
        "/系统维护/图吧 工具箱+2025#1?.exe", "signature:123"
    )
    assert entry.host == "alist.example.com"
    assert entry.base_path == "/软件"
    assert entry.has_sign is True
    assert entry.url == "https://alist.example.com/cloudsite/d/%E8%BD%AF%E4%BB%B6/%E7%B3%BB%E7%BB%9F%E7%BB%B4%E6%8A%A4/%E5%9B%BE%E5%90%A7%20%E5%B7%A5%E5%85%B7%E7%AE%B1%2B2025%231%3F.exe?sign=signature%3A123"


def test_alist_native_download_entry_allows_missing_sign_and_rejects_host_mismatch():
    entry = AListUrlBuilder("https://alist.example.com", "/").build_download_entry("/Docs/[a]&b.txt")
    assert entry.url == "https://alist.example.com/d/Docs/%5Ba%5D%26b.txt"
    assert entry.has_sign is False
    with pytest.raises(DownloadError) as raised:
        validate_download_url(entry.url, "other.example.com")
    assert raised.value.code == "DL-008"


def test_download_url_cache_supports_hit_expiry_force_invalidation_and_capacity():
    cache = DownloadUrlCache(ttl_seconds=10, max_entries=2)
    cache.set("r1", "https://cdn.example/r1", now=100)
    assert cache.get("r1", now=109) == "https://cdn.example/r1"
    assert cache.get("r1", now=110) is None
    cache.set("r1", "https://cdn.example/r1", now=200)
    cache.set("r2", "https://cdn.example/r2", now=200)
    cache.set("r3", "https://cdn.example/r3", now=200)
    assert cache.get("r1", now=201) is None
    cache.invalidate("r2")
    assert cache.get("r2", now=201) is None


def test_download_alist_errors_map_to_public_dl_codes_without_upstream_text():
    assert map_alist_error(AListError("secret network detail", "AL-002")).code == "DL-002"
    assert map_alist_error(AListError("file metadata unavailable", "AL-005")).code == "DL-003"
    assert map_alist_error(AListError("auth failed", "AL-004")).code == "DL-006"
    mapped = map_alist_error(RuntimeError("private traceback"))
    assert mapped.code == "DL-999"
    assert "private traceback" not in mapped.message


def test_preview_capability_uses_extension_and_never_claims_iso_or_exe_previewable():
    def resource(name, extension, mime_type="", status="active"):
        return SimpleNamespace(id="r1", name=name, extension=extension, mime_type=mime_type, status=status)

    assert preview_capability(resource("image.jpg", "jpg"))["preview_type"] == "image"
    assert preview_capability(resource("movie.mp4", "mp4"))["preview_type"] == "video"
    assert preview_capability(resource("manual.pdf", "pdf"))["preview_type"] == "pdf"
    assert preview_capability(resource("readme.md", "md"))["preview_type"] == "markdown"
    assert preview_capability(resource("installer.exe", "exe"))["preview_type"] == "none"
    assert preview_capability(resource("missing.jpg", "jpg", status="missing"))["can_preview"] is False


def test_preview_capability_detects_office_formats():
    def resource(name, extension):
        return SimpleNamespace(id="r1", name=name, extension=extension, mime_type="", status="active")

    assert preview_capability(resource("slide.pptx", "pptx"))["preview_type"] == "office"
    assert preview_capability(resource("sheet.xlsx", "xlsx"))["preview_type"] == "office"
    assert preview_capability(resource("doc.docx", "docx"))["preview_type"] == "office"
    assert preview_capability(resource("legacy.doc", "doc"))["preview_type"] == "office"
    assert preview_capability(resource("legacy.xls", "xls"))["preview_type"] == "office"
    assert preview_capability(resource("legacy.ppt", "ppt"))["preview_type"] == "office"
    assert preview_capability(resource("book.pdf", "pdf"))["preview_type"] == "pdf"


def test_preview_uses_same_safe_http_url_policy_as_download():
    assert validate_download_url("https://preview.example.com/file.jpg")[1] == "preview.example.com"
    with pytest.raises(DownloadError):
        validate_download_url("data:text/html,unsafe")
