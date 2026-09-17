from __future__ import annotations

from datetime import datetime, timedelta, timezone

_DEFAULT_BACKOFF = [0, 30, 120, 600, 1800]


class RetryPolicy:
    def __init__(self, backoff_seconds: list[float] | None = None) -> None:
        self._backoff = backoff_seconds or _DEFAULT_BACKOFF

    def get_delay(self, attempt_count: int) -> float:
        idx = min(attempt_count - 1, len(self._backoff) - 1)
        return self._backoff[idx]

    def get_retry_at(self, attempt_count: int, *, now: datetime | None = None) -> datetime:
        delay = self.get_delay(attempt_count)
        base = now or datetime.now(timezone.utc)
        return base + timedelta(seconds=delay)

    def should_retry(self, attempt_count: int, max_attempts: int) -> bool:
        return attempt_count < max_attempts


default_retry_policy = RetryPolicy()


__all__ = ['RetryPolicy', 'default_retry_policy']
