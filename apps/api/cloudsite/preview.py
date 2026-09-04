from dataclasses import dataclass
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

from .alist import AListClient, AListError
from .config import settings
from .crypto import decrypt_secret
from .download import DownloadUrlCache, validate_download_url


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif", "svg"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "mkv", "avi"}
TEXT_EXTENSIONS = {"txt", "json", "yaml", "yml", "log", "ini", "conf", "csv"}
MARKDOWN_EXTENSIONS = {"md", "markdown"}
OFFICE_EXTENSIONS = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}
OFFICE_MIME_TYPES = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PREVIEW_TICKET_TTL_SECONDS = 6 * 60 * 60


class PreviewError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class PreviewResolution:
    url: str
    target_host: str
    cache_hit: bool


preview_url_cache = DownloadUrlCache(settings.preview_cache_ttl_seconds, settings.preview_cache_max_entries)
logger = logging.getLogger(__name__)


def create_preview_ticket(resource_id: str, now: int | None = None) -> str:
    expires_at = int(time.time() if now is None else now) + PREVIEW_TICKET_TTL_SECONDS
    payload = f"{resource_id}:{expires_at}"
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def validate_preview_ticket(resource_id: str, ticket: str | None, now: int | None = None) -> bool:
    if not ticket or "." not in ticket:
        return False
    expires_text, signature = ticket.split(".", 1)
    if not expires_text.isdigit() or int(expires_text) < int(time.time() if now is None else now):
        return False
    payload = f"{resource_id}:{expires_text}"
    expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def preview_capability(resource) -> dict:
    extension = (getattr(resource, "extension", "") or "").lower().lstrip(".")
    mime_type = (getattr(resource, "mime_type", "") or "").lower()
    if extension in IMAGE_EXTENSIONS or mime_type.startswith("image/"):
        preview_type = "image"
    elif extension in VIDEO_EXTENSIONS or mime_type.startswith("video/"):
        preview_type = "video"
    elif extension == "pdf" or mime_type == "application/pdf":
        preview_type = "pdf"
    elif extension in OFFICE_EXTENSIONS or mime_type in OFFICE_MIME_TYPES:
        preview_type = "office"
    elif extension in MARKDOWN_EXTENSIONS:
        preview_type = "markdown"
    elif extension in TEXT_EXTENSIONS or mime_type.startswith("text/"):
        preview_type = "text"
    else:
        preview_type = "none"
    can_preview = preview_type != "none" and getattr(resource, "status", "active") == "active"
    reason = "" if can_preview else ("资源当前不可用" if getattr(resource, "status", "active") != "active" else "当前文件格式不支持在线预览")
    gateway_url = ""
    if can_preview and preview_type not in {"text", "markdown", "office"}:
        gateway_url = f"/p/{resource.id}?{urlencode({'ticket': create_preview_ticket(resource.id)})}"
    return {
        "preview_type": preview_type,
        "can_preview": can_preview,
        "preview_mode": "text" if preview_type in {"text", "markdown"} else "office" if preview_type == "office" else "direct" if can_preview else "none",
        "browser_native": preview_type in {"image", "video", "pdf", "office"},
        "mime_type": mime_type,
        "extension": extension,
        "reason": reason,
        "gateway_url": gateway_url,
        "can_download": getattr(resource, "status", "active") == "active",
    }


def _map_alist_preview_error(exc: Exception) -> PreviewError:
    if isinstance(exc, AListError):
        if exc.code == "AL-002":
            return PreviewError("PV-005", "上游存储暂时不可用", 503)
        if exc.code in {"AL-003", "AL-004"}:
            return PreviewError("PV-005", "预览服务认证状态失效", 503)
        if exc.code == "AL-005":
            return PreviewError("PV-003", "无法获取预览入口")
    return PreviewError("PV-999", "预览服务暂时不可用")


async def resolve_preview_url(resource, connection, force_refresh: bool = False) -> PreviewResolution:
    capability = preview_capability(resource)
    if not capability["can_preview"] or capability["preview_type"] in {"text", "markdown"}:
        raise PreviewError("PV-002", capability["reason"] or "资源不支持直接预览", 400)
    if force_refresh:
        preview_url_cache.invalidate(resource.id)
    cached = preview_url_cache.get(resource.id)
    if cached:
        try:
            url, host = validate_download_url(cached)
            return PreviewResolution(url, host, True)
        except Exception:
            preview_url_cache.invalidate(resource.id)
    if not connection or not connection.enabled:
        raise PreviewError("PV-005", "上游存储暂时不可用", 503)
    try:
        password = decrypt_secret(connection.password_ciphertext)
        async with AListClient(connection.base_url, connection.username, password) as client:
            provider_started = time.perf_counter()
            entry = await client.get_preview_entry(resource.path)
            logger.debug(
                "preview metrics resource_id=%s provider_lookup_ms=%.2f",
                resource.id,
                (time.perf_counter() - provider_started) * 1000,
            )
    except Exception as exc:
        raise _map_alist_preview_error(exc) from exc
    try:
        url, host = validate_download_url(entry.url, entry.host)
    except Exception as exc:
        raise PreviewError("PV-008", "预览地址安全校验失败") from exc
    preview_url_cache.set(resource.id, url)
    return PreviewResolution(url, host, False)


async def load_text_preview(resource, connection) -> dict:
    capability = preview_capability(resource)
    if not capability["can_preview"] or capability["preview_type"] not in {"text", "markdown"}:
        raise PreviewError("PV-002", capability["reason"] or "资源不支持文本预览", 400)
    if resource.size > settings.text_preview_max_bytes:
        raise PreviewError("PV-007", "文本文件过大，不提供在线预览", 413)
    if not connection or not connection.enabled:
        raise PreviewError("PV-005", "上游存储暂时不可用", 503)
    try:
        password = decrypt_secret(connection.password_ciphertext)
        async with AListClient(connection.base_url, connection.username, password) as client:
            entry = await client.get_preview_entry(resource.path)
        url, _ = validate_download_url(entry.url, entry.host)
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"Range": f"bytes=0-{settings.text_preview_max_bytes}"}) as response:
                response.raise_for_status()
                total = _response_total_size(response)
                if total is not None and total > settings.text_preview_max_bytes:
                    raise PreviewError("PV-007", "文本文件过大，不提供在线预览", 413)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining = settings.text_preview_max_bytes + 1 - len(content)
                    content.extend(chunk[:remaining])
                    if len(content) > settings.text_preview_max_bytes:
                        raise PreviewError("PV-007", "文本文件过大，不提供在线预览", 413)
    except PreviewError:
        raise
    except Exception as exc:
        raise _map_alist_preview_error(exc) from exc
    return {
        "content": bytes(content).decode("utf-8", errors="replace"),
        "truncated": False,
        "size": resource.size,
        "encoding": "utf-8",
        "preview_type": capability["preview_type"],
    }


def _response_total_size(response: httpx.Response) -> int | None:
    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[-1]
        if total.isdigit():
            return int(total)
    content_length = response.headers.get("content-length", "")
    return int(content_length) if content_length.isdigit() else None
