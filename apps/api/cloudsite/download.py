"""Compatibility facade for Delivery-owned download behavior."""

from .alist import AListClient, AListError
from .crypto import decrypt_secret
from .modules.delivery.domain.download import (
    DownloadError,
    DownloadResolution,
    DownloadUrlCache,
    RESOURCE_ID_PATTERN,
    map_provider_error,
    resolve_download_entry,
    validate_download_url,
    validate_resource_id,
)


def map_alist_error(exc: Exception) -> DownloadError:
    """Legacy AList error mapping kept for compatibility callers/tests."""
    if not isinstance(exc, AListError):
        return DownloadError(
            "DL-999",
            "download service temporarily unavailable",
            "download_entry",
        )
    if exc.status_code == 429:
        return DownloadError(
            "DL-003",
            "cannot read AList file info",
            "alist_file_info",
            429,
        )
    if exc.code == "AL-002":
        return DownloadError(
            "DL-002",
            "AList temporarily unreachable",
            "alist_connection",
            503,
        )
    if exc.code in {"AL-003", "AL-004"}:
        return DownloadError(
            "DL-006",
            "AList authentication failed",
            "authentication",
            503,
        )
    if exc.code == "AL-005":
        return DownloadError(
            "DL-003",
            "cannot read AList file info",
            "alist_file_info",
            503,
        )
    return DownloadError(
        "DL-999",
        "download service temporarily unavailable",
        "download_entry",
    )


__all__ = [
    "DownloadError",
    "DownloadResolution",
    "DownloadUrlCache",
    "RESOURCE_ID_PATTERN",
    "validate_resource_id",
    "validate_download_url",
    "map_alist_error",
    "map_provider_error",
    "resolve_download_entry",
    "AListClient",
    "AListError",
    "decrypt_secret",
]
