import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx

from .config import settings


class AListError(RuntimeError):
    def __init__(
        self,
        message: str,
        code: str = "AL-999",
        *,
        status_code: int = 502,
        auth_failed: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.auth_failed = auth_failed


@dataclass(frozen=True, slots=True)
class AListDownloadEntry:
    """AList's own download endpoint, not a storage-provider raw URL."""

    url: str
    host: str
    base_path: str
    has_sign: bool


class AListUrlBuilder:
    """Build a native AList /d/ URL while preserving its site and user paths."""

    def __init__(self, base_url: str, base_path: str = "/") -> None:
        parsed = urlsplit(base_url.strip().rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise AListError("AList 地址无效", "AL-001", status_code=400)
        if parsed.query or parsed.fragment:
            raise AListError("AList 地址不能包含查询参数或片段", "AL-001", status_code=400)
        self._parsed = parsed
        self._base_path = self._path_segments(base_path)

    @staticmethod
    def _path_segments(value: str) -> list[str]:
        cleaned = (value or "/").replace("\\", "/").strip()
        parts = [part for part in cleaned.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise AListError("AList 路径无效", "AL-005", status_code=502)
        return parts

    @staticmethod
    def _encode_segments(parts: list[str]) -> str:
        return "/".join(quote(part, safe="") for part in parts)

    def build_download_entry(self, visible_path: str, sign: str = "") -> AListDownloadEntry:
        site_parts = self._path_segments(self._parsed.path)
        visible_parts = self._path_segments(visible_path)
        encoded_parts = self._encode_segments([*site_parts, "d", *self._base_path, *visible_parts])
        path = f"/{encoded_parts}" if encoded_parts else "/d"
        query = urlencode({"sign": sign}) if sign else ""
        url = urlunsplit((self._parsed.scheme, self._parsed.netloc, path, query, ""))
        base_path = "/" + "/".join(self._base_path) if self._base_path else "/"
        return AListDownloadEntry(url=url, host=self._parsed.hostname, base_path=base_path, has_sign=bool(sign))


@dataclass(slots=True)
class AListClient:
    base_url: str
    username: str
    password: str
    token: str = ""
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.strip().rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise AListError("AList 地址无效，请填写完整的 http:// 或 https:// 地址", "AL-001", status_code=400)

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        )
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["Authorization"] = self.token
        try:
            response = None
            for attempt in range(3):
                request_client = self._client or httpx.AsyncClient(
                    timeout=settings.request_timeout_seconds,
                    follow_redirects=False,
                )
                try:
                    response = await request_client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=headers,
                        **kwargs,
                    )
                    break
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.3 * (2 ** attempt))
                finally:
                    if self._client is None:
                        await request_client.aclose()
            if response is None:
                raise AListError("AList 未返回响应", "AL-002", status_code=502)
        except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
            raise AListError("AList 地址无效", "AL-001", status_code=400) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AListError("无法连接 AList，请检查地址和网络", "AL-002", status_code=502) from exc
        except Exception as exc:
            raise AListError("请求 AList 时发生未知错误", "AL-999", status_code=502) from exc

        if response.status_code in {401, 403}:
            raise AListError(
                "AList 登录状态已失效或账号无权访问",
                "AL-004",
                status_code=401,
                auth_failed=True,
            )
        if response.status_code == 429:
            raise AListError("AList 请求过于频繁", "AL-005", status_code=429)
        if response.status_code >= 400:
            raise AListError(f"AList HTTP {response.status_code}", "AL-005", status_code=502)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AListError("AList 返回了非 JSON 响应", "AL-005", status_code=502) from exc
        if not isinstance(payload, dict):
            raise AListError("AList 响应格式异常", "AL-005", status_code=502)

        result_code = payload.get("code")
        if result_code not in (200, 0):
            message = str(payload.get("message") or "AList 请求失败")
            auth_failed = result_code in {401, 403} or any(
                keyword in message.lower() for keyword in ("unauthorized", "token", "password", "login")
            )
            raise AListError(
                message,
                "AL-004" if auth_failed else "AL-005",
                status_code=401 if auth_failed else 502,
                auth_failed=auth_failed,
            )
        return payload

    async def login(self) -> None:
        try:
            payload = await self._request(
                "POST",
                "/api/auth/login",
                json={"username": self.username, "password": self.password},
            )
        except AListError as exc:
            if exc.code in {"AL-001", "AL-002", "AL-004"}:
                raise
            raise AListError("AList 登录失败", "AL-003", status_code=401, auth_failed=True) from exc
        self.token = str((payload.get("data") or {}).get("token") or "")
        if not self.token:
            raise AListError("AList 登录成功但未返回 Token", "AL-003", status_code=502)

    async def _authenticated_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.token:
            await self.login()
        try:
            return await self._request(method, path, **kwargs)
        except AListError as exc:
            if not exc.auth_failed:
                raise
        self.token = ""
        await self.login()
        return await self._request(method, path, **kwargs)

    async def list_path(self, path: str) -> list[dict[str, Any]]:
        payload = await self._authenticated_request(
            "POST",
            "/api/fs/list",
            json={"path": path, "password": "", "page": 1, "per_page": 0, "refresh": False},
        )
        content = (payload.get("data") or {}).get("content") or []
        if not isinstance(content, list):
            raise AListError("AList 目录响应格式异常", "AL-005", status_code=502)
        return content

    async def list_directories(self, path: str) -> list[dict[str, Any]]:
        items = await self.list_path(path)
        return sorted(
            (item for item in items if item.get("is_dir") and item.get("name")),
            key=lambda item: str(item.get("name", "")).casefold(),
        )

    async def get_path(self, path: str) -> dict[str, Any]:
        payload = await self._authenticated_request(
            "POST",
            "/api/fs/get",
            json={"path": path, "password": ""},
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise AListError("AList 文件响应格式异常", "AL-005", status_code=502)
        return data

    async def get_file_info(self, path: str) -> dict[str, Any]:
        item = await self.get_path(path)
        return {
            "name": str(item.get("name") or path.rstrip("/").rsplit("/", 1)[-1]),
            "is_dir": bool(item.get("is_dir")),
            "size": int(item.get("size") or 0),
            "modified": item.get("modified") or item.get("updated_at"),
            "path": path,
        }

    async def get_download_url(self, path: str) -> str:
        """Compatibility method for preview only; downloads use get_download_entry."""
        item = await self.get_path(path)
        url = str(item.get("raw_url") or item.get("url") or "")
        if not url:
            raise AListError("AList 未返回可用的下载地址", "AL-005", status_code=502)
        return url

    async def get_base_path(self) -> str:
        payload = await self._authenticated_request("GET", "/api/me")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise AListError("AList 用户信息响应格式异常", "AL-005", status_code=502)
        return str(data.get("base_path") or "/")

    async def get_download_entry(self, path: str) -> AListDownloadEntry:
        item = await self.get_path(path)
        if bool(item.get("is_dir")):
            raise AListError("当前对象是目录，不能作为单文件下载", "AL-005", status_code=400)
        base_path = await self.get_base_path()
        return AListUrlBuilder(self.base_url, base_path).build_download_entry(path, str(item.get("sign") or ""))

    async def get_preview_entry(self, path: str) -> AListDownloadEntry:
        """Return an AList-native /d/ entry so the redirect host stays the configured AList host.

        M6 不自行解析最终网盘直链；预览与下载一样 302 到 AList 原生入口，
        Content-Disposition / Range / 最终直链继续由 AList 与 Storage Driver 处理。
        """
        return await self.get_download_entry(path)

    async def get_storage_info(self, base_path: str = "") -> dict:
        """Return AList storage names, with the primary one matching base_path."""
        drives: list[str] = []
        try:
            payload = await self._authenticated_request("GET", "/api/admin/storage/list")
            data = payload.get("data") or {}
            rows = data.get("content") if isinstance(data, dict) else data
            if isinstance(rows, list):
                for row in rows:
                    mount = str(row.get("mount_path") or "").strip("/")
                    if mount:
                        drives.append(mount)
        except Exception:
            pass
        if not drives:
            try:
                payload = await self._authenticated_request(
                    "POST", "/api/fs/list",
                    json={"path": "/", "password": "", "page": 1, "per_page": 0, "refresh": False},
                )
                provider = str((payload.get("data") or {}).get("provider") or "").strip()
                if provider:
                    drives = [provider]
            except Exception:
                pass
        first_segment = base_path.strip("/").split("/")[0] if base_path else ""
        primary = ""
        for drive in drives:
            if drive == first_segment or (first_segment and (first_segment in drive or drive in first_segment)):
                primary = drive
                break
        if not primary:
            primary = first_segment or (drives[0] if drives else "网盘")
        return {"primary": primary, "drives": drives}

    async def test(self) -> dict[str, Any]:
        await self.login()
        base_path = await self.get_base_path()
        items = await self.list_path("/")
        return {"ok": True, "message": "AList 连接及根目录访问成功", "item_count": len(items), "base_path": base_path}


AListProvider = AListClient
