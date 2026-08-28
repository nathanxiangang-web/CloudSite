import time
from pathlib import Path

import httpx

from .alist import AListClient
from .config import settings
from .crypto import decrypt_secret
from .download import validate_download_url


OFFICE_CONTENT_TYPES = {
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


class OfficePreviewError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def office_content_type(extension: str) -> str:
    return OFFICE_CONTENT_TYPES.get((extension or "").lower().lstrip("."), "application/octet-stream")


def office_cache_filename(resource) -> str:
    extension = (resource.extension or "bin").lower().lstrip(".")
    return f"{resource.id}.{extension}"


def office_cache_path(resource) -> Path:
    return settings.office_cache_dir / office_cache_filename(resource)


def sweep_office_cache() -> None:
    cache_dir = settings.office_cache_dir
    if not cache_dir.exists():
        return
    now = time.time()
    for path in cache_dir.glob("*"):
        if path.is_file() and (now - path.stat().st_mtime) > settings.office_cache_ttl_seconds:
            path.unlink(missing_ok=True)


async def ensure_preview_cached(resource, connection) -> Path:
    """Return the local cached path for a binary preview file (Office/PDF), downloading it if stale/missing."""
    settings.office_cache_dir.mkdir(parents=True, exist_ok=True)
    sweep_office_cache()
    path = office_cache_path(resource)
    if path.exists() and (time.time() - path.stat().st_mtime) < settings.office_cache_ttl_seconds:
        return path
    if not connection or not connection.enabled:
        raise OfficePreviewError("PV-005", "上游存储暂时不可用", 503)
    try:
        password = decrypt_secret(connection.password_ciphertext)
        async with AListClient(connection.base_url, connection.username, password) as client:
            url = await client.get_download_url(resource.path)
        url, _ = validate_download_url(url)
    except Exception as exc:
        raise OfficePreviewError("PV-003", "无法获取 Office 预览入口", 503) from exc
    tmp_path = path.with_name(path.name + ".part")
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = 0
                with tmp_path.open("wb") as file_handle:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > settings.office_cache_max_bytes:
                            raise OfficePreviewError("PV-007", "文件过大，无法缓存预览", 413)
                        file_handle.write(chunk)
        tmp_path.replace(path)
    except OfficePreviewError:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfficePreviewError("PV-999", "Office 预览缓存下载失败") from exc
    return path
