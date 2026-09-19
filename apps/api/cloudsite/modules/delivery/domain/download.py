import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urlparse

from cloudsite.modules.providers.contracts.public import (
    ProviderAccessError,
    ProviderRuntimePort,
    ProviderUnavailableError,
)


RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DownloadError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        failed_step: str,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.failed_step = failed_step
        self.status_code = status_code


@dataclass(slots=True)
class DownloadResolution:
    url: str
    target_host: str
    base_path: str
    has_sign: bool
    steps: list[dict] = field(default_factory=list)


class DownloadUrlCache:
    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._items: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def get(self, resource_id: str, now: float | None = None) -> str | None:
        value = self._items.get(resource_id)
        if not value:
            return None
        current = time.monotonic() if now is None else now
        url, expires_at = value
        if expires_at <= current:
            self._items.pop(resource_id, None)
            return None
        self._items.move_to_end(resource_id)
        return url

    def set(self, resource_id: str, url: str, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self._items[resource_id] = (url, current + self.ttl_seconds)
        self._items.move_to_end(resource_id)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def invalidate(self, resource_id: str) -> None:
        self._items.pop(resource_id, None)

    def clear(self) -> None:
        self._items.clear()


def validate_resource_id(resource_id: str) -> bool:
    return bool(RESOURCE_ID_PATTERN.fullmatch(resource_id))


def validate_download_url(
    value: str,
    expected_host: str | None = None,
) -> tuple[str, str]:
    if not value or any(ord(character) < 32 for character in value):
        raise DownloadError(
            "DL-008",
            "download URL safety check failed",
            "url_validation",
        )
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise DownloadError(
            "DL-008",
            "download URL safety check failed",
            "url_validation",
        )
    if expected_host and parsed.hostname.lower() != expected_host.lower():
        raise DownloadError(
            "DL-008",
            "download entry safety check failed",
            "redirect_validation",
        )
    return value, parsed.hostname


def map_provider_error(exc: Exception) -> DownloadError:
    if isinstance(exc, ProviderUnavailableError):
        return DownloadError(
            "DL-002",
            "storage provider is unavailable",
            "alist_connection",
            503,
        )
    if isinstance(exc, ProviderAccessError):
        if exc.status_code == 429:
            return DownloadError(
                "DL-003",
                "cannot read provider file info",
                "alist_file_info",
                429,
            )
        if exc.category == "unreachable":
            return DownloadError(
                "DL-002",
                "storage provider temporarily unreachable",
                "alist_connection",
                503,
            )
        if exc.category in {"authentication", "credentials"}:
            return DownloadError(
                "DL-006",
                "storage provider authentication failed",
                "authentication",
                503,
            )
        if exc.category == "metadata":
            return DownloadError(
                "DL-003",
                "cannot read provider file info",
                "alist_file_info",
                503,
            )
    return DownloadError(
        "DL-999",
        "download service temporarily unavailable",
        "download_entry",
    )


async def resolve_download_entry(
    resource,
    provider_runtime: ProviderRuntimePort,
) -> DownloadResolution:
    steps: list[dict] = []
    started = time.perf_counter()
    try:
        entry = await provider_runtime.download_entry(
            root_mapping_id=resource.root_mapping_id,
            path=resource.path,
        )
        fetch_ms = int((time.perf_counter() - started) * 1000)
        steps.extend(
            [
                {
                    "name": "alist_connection",
                    "status": "success",
                    "duration_ms": 0,
                },
                {
                    "name": "authentication",
                    "status": "success",
                    "duration_ms": fetch_ms,
                },
                {
                    "name": "alist_file_info",
                    "status": "success",
                    "duration_ms": fetch_ms,
                },
                {
                    "name": "base_path_resolve",
                    "status": "success",
                    "duration_ms": 0,
                },
                {
                    "name": "download_sign",
                    "status": "success" if entry.has_sign else "skipped",
                    "duration_ms": 0,
                },
                {
                    "name": "download_entry_build",
                    "status": "success",
                    "duration_ms": 0,
                },
            ]
        )
    except Exception as exc:
        raise map_provider_error(exc) from exc

    validation_started = time.perf_counter()
    url, host = validate_download_url(entry.url, entry.host)
    steps.append(
        {
            "name": "redirect_validation",
            "status": "success",
            "duration_ms": int(
                (time.perf_counter() - validation_started) * 1000
            ),
        }
    )
    steps.append(
        {"name": "redirect_ready", "status": "success", "duration_ms": 0}
    )
    return DownloadResolution(
        url,
        host,
        entry.base_path,
        entry.has_sign,
        steps,
    )


__all__ = [
    "DownloadError",
    "DownloadResolution",
    "DownloadUrlCache",
    "RESOURCE_ID_PATTERN",
    "validate_resource_id",
    "validate_download_url",
    "map_provider_error",
    "resolve_download_entry",
]
