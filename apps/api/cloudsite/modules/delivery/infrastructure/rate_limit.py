"""Compatibility facade for Resources-owned download rate limiting."""

from cloudsite.modules.resources.contracts.public import (
    DOWNLOAD_RATE_BLOCK_SECONDS,
    DOWNLOAD_RATE_CLEANUP_SECONDS,
    DOWNLOAD_RATE_MAX_ATTEMPTS,
    DOWNLOAD_RATE_WINDOW_SECONDS,
    DownloadRateDecision,
    check_download_rate,
    cleanup_download_rate_limits,
    get_effective_client_ip,
    hash_ip,
    rate_limit_payload,
)

__all__ = [
    "DOWNLOAD_RATE_MAX_ATTEMPTS",
    "DOWNLOAD_RATE_WINDOW_SECONDS",
    "DOWNLOAD_RATE_BLOCK_SECONDS",
    "DOWNLOAD_RATE_CLEANUP_SECONDS",
    "DownloadRateDecision",
    "get_effective_client_ip",
    "hash_ip",
    "check_download_rate",
    "cleanup_download_rate_limits",
    "rate_limit_payload",
]
