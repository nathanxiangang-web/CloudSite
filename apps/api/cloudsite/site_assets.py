from __future__ import annotations

import secrets
from pathlib import Path

from .config import settings


SHARE_IMAGE_MAX_BYTES = 8 * 1024 * 1024


def share_image_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def share_image_directory() -> Path:
    return settings.data_dir / "site-assets"


def share_image_path(name: str) -> Path | None:
    if not name or Path(name).name != name or not name.startswith("share-page-"):
        return None
    path = share_image_directory() / name
    return path if path.is_file() else None


def save_share_image(data: bytes) -> str:
    extension = share_image_extension(data)
    if extension is None:
        raise ValueError("仅支持 PNG、JPEG 或 WebP 图片")
    directory = share_image_directory()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"share-page-{secrets.token_hex(8)}.{extension}"
    target = directory / name
    temporary = directory / f".{name}.upload"
    temporary.write_bytes(data)
    temporary.replace(target)
    return name


def remove_share_image(name: str) -> None:
    path = share_image_path(name)
    if path:
        path.unlink(missing_ok=True)
