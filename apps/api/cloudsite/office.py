import re
import subprocess
import time
from pathlib import Path

import httpx

from .config import settings
from .download import validate_download_url
from .modules.providers.contracts.public import (
    ProviderAccessError,
    ProviderRuntimePort,
    ProviderUnavailableError,
)


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
        elif path.is_dir() and path.name.endswith("_pages"):
            try:
                if not any(path.iterdir()) or all((now - p.stat().st_mtime) > settings.office_cache_ttl_seconds for p in path.iterdir()):
                    for p in path.iterdir():
                        p.unlink(missing_ok=True)
                    path.rmdir()
            except OSError:
                pass


def _page_number(name: str) -> int:
    match = re.search(r"-(\d+)\.png$", name)
    return int(match.group(1)) if match else 0


def render_pdf_pages(resource) -> list[str]:
    """把缓存 PDF 转成每页 PNG，返回按页码排序的文件名列表（page-N.png）。"""
    pdf_path = office_cache_path(resource)
    if not pdf_path.is_file():
        raise OfficePreviewError("PV-004", "预览文件不存在或已过期", 404)
    pages_dir = settings.office_cache_dir / f"{resource.id}_pages"
    now = time.time()
    cached = sorted(pages_dir.glob("page-*.png"), key=lambda p: _page_number(p.name)) if pages_dir.exists() else []
    if cached and all((now - p.stat().st_mtime) < settings.office_cache_ttl_seconds for p in cached):
        return [p.name for p in cached]
    pages_dir.mkdir(parents=True, exist_ok=True)
    for path in pages_dir.glob("*.png"):
        path.unlink(missing_ok=True)
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", "120", str(pdf_path), str(pages_dir / "page")],
            check=True, capture_output=True, timeout=60,
        )
    except FileNotFoundError as exc:
        raise OfficePreviewError("PV-010", "服务器缺少 PDF 渲染组件", 503) from exc
    except Exception as exc:
        raise OfficePreviewError("PV-999", "PDF 渲染失败") from exc
    rendered = sorted(pages_dir.glob("page-*.png"), key=lambda p: _page_number(p.name))
    if not rendered:
        raise OfficePreviewError("PV-999", "PDF 渲染失败（无页面输出）")
    return [p.name for p in rendered]


async def ensure_preview_cached(
    resource,
    provider_runtime: ProviderRuntimePort,
) -> Path:
    """Return a locally cached preview file through the Providers runtime boundary."""
    settings.office_cache_dir.mkdir(parents=True, exist_ok=True)
    sweep_office_cache()
    path = office_cache_path(resource)
    if path.exists() and (time.time() - path.stat().st_mtime) < settings.office_cache_ttl_seconds:
        return path

    root_mapping_id = getattr(resource, "root_mapping_id", None)
    if root_mapping_id is None:
        raise OfficePreviewError("PV-005", "上游存储暂时不可用", 503)

    try:
        entry = await provider_runtime.download_entry(
            root_mapping_id=root_mapping_id,
            path=resource.path,
        )
        url, _ = validate_download_url(entry.url, entry.host)
    except ProviderUnavailableError as exc:
        raise OfficePreviewError("PV-005", "上游存储暂时不可用", 503) from exc
    except ProviderAccessError as exc:
        raise OfficePreviewError("PV-003", "无法获取 Office 预览入口", 503) from exc
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

