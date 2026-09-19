"""Resources-owned preview cache primitives."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from ....config import settings
from ....download import validate_download_url
from ..domain.preview import ResourcePreviewError
from ..domain.views import ResourcePreviewView


def preview_cache_filename(resource: ResourcePreviewView) -> str:
    extension = (resource.extension or "bin").lower().lstrip(".")
    return f"{resource.id}.{extension}"


def preview_cache_path(resource: ResourcePreviewView) -> Path:
    return settings.office_cache_dir / preview_cache_filename(resource)


def _sweep_preview_cache() -> None:
    cache_dir = settings.office_cache_dir
    if not cache_dir.exists():
        return

    now = time.time()
    for path in cache_dir.glob("*"):
        if path.is_file() and (
            now - path.stat().st_mtime
        ) > settings.office_cache_ttl_seconds:
            path.unlink(missing_ok=True)
        elif path.is_dir() and path.name.endswith("_pages"):
            try:
                children = list(path.iterdir())
                if not children or all(
                    (now - child.stat().st_mtime)
                    > settings.office_cache_ttl_seconds
                    for child in children
                ):
                    for child in children:
                        child.unlink(missing_ok=True)
                    path.rmdir()
            except OSError:
                pass


def fresh_preview_cache_path(
    resource: ResourcePreviewView,
) -> Path | None:
    settings.office_cache_dir.mkdir(parents=True, exist_ok=True)
    _sweep_preview_cache()
    path = preview_cache_path(resource)
    if path.exists() and (
        time.time() - path.stat().st_mtime
    ) < settings.office_cache_ttl_seconds:
        return path
    return None


async def cache_preview_from_url(
    resource: ResourcePreviewView,
    source_url: str,
) -> Path:
    settings.office_cache_dir.mkdir(parents=True, exist_ok=True)
    path = preview_cache_path(resource)

    try:
        url, _host = validate_download_url(source_url)
    except Exception as exc:
        raise ResourcePreviewError(
            "PV-003",
            "无法获取 Office 预览入口",
            503,
        ) from exc

    tmp_path = path.with_name(path.name + ".part")
    try:
        async with httpx.AsyncClient(
            timeout=120.0,
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = 0
                with tmp_path.open("wb") as file_handle:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > settings.office_cache_max_bytes:
                            raise ResourcePreviewError(
                                "PV-007",
                                "文件过大，无法缓存预览",
                                413,
                            )
                        file_handle.write(chunk)
        tmp_path.replace(path)
    except ResourcePreviewError:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise ResourcePreviewError(
            "PV-999",
            "Office 预览缓存下载失败",
        ) from exc

    return path


__all__ = [
    "cache_preview_from_url",
    "fresh_preview_cache_path",
    "preview_cache_filename",
    "preview_cache_path",
]
