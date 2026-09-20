"""Test-only fault injection harness for Provider implementations.

V2 doc section 73 requires fault injection capability.  This module provides
a pure test-infrastructure wrapper that surrounds any Provider (real or fake)
and injects failures, latency, malformed payloads, rate-limiting, and
disconnections according to declarative rules.  It never modifies production
code paths; it is imported only from test modules.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any


class ProviderRateLimitError(Exception):
    """Raised by FaultInjector to simulate upstream rate limiting."""


class ProviderDisconnectError(Exception):
    """Raised by FaultInjector to simulate an upstream connection drop."""


_MALFORMED_SENTINEL: dict[str, Any] = {"__fault_injection_malformed__": True}


class FaultInjector:
    """Wrapper that injects faults into any Provider implementation.

    The injector proxies attribute access to the wrapped provider.  Async
    methods are intercepted so configured fault rules can raise exceptions,
    introduce latency, or substitute malformed/empty return values.  Sync
    attributes (such as ``adapter_version`` and ``capabilities``) pass through
    untouched.  Paths and request counts that have no configured fault behave
    exactly as the underlying provider would.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self._request_count = 0
        self._fail_paths: dict[str, Exception] = {}
        self._delay_paths: dict[str, float] = {}
        self._malformed_paths: set[str] = set()
        self._empty_paths: set[str] = set()
        self._fail_after_n: tuple[int, Exception] | None = None
        self._rate_limit_after_n: int | None = None
        self._disconnect_after_n: int | None = None

    # -- configuration API -------------------------------------------------
    def fail_on_path(self, path: str, exc: Exception) -> "FaultInjector":
        """Raise *exc* on any async call whose first positional arg is *path*."""
        self._fail_paths[path] = exc
        return self

    def fail_after_n_requests(self, n: int, exc: Exception) -> "FaultInjector":
        """Let the first *n* calls succeed, then raise *exc* on every later call."""
        self._fail_after_n = (n, exc)
        return self

    def delay_on_path(self, path: str, seconds: float) -> "FaultInjector":
        """Insert *seconds* of await latency before delegating calls for *path*."""
        self._delay_paths[path] = seconds
        return self

    def return_malformed_on_path(self, path: str) -> "FaultInjector":
        """Return a malformed sentinel instead of delegating calls for *path*."""
        self._malformed_paths.add(path)
        return self

    def return_empty_on_path(self, path: str) -> "FaultInjector":
        """Return an empty list instead of delegating calls for *path*."""
        self._empty_paths.add(path)
        return self

    def rate_limit_after_n(self, n: int) -> "FaultInjector":
        """Let the first *n* calls succeed, then raise ProviderRateLimitError."""
        self._rate_limit_after_n = n
        return self

    def disconnect_after_n(self, n: int) -> "FaultInjector":
        """Let the first *n* calls succeed, then raise ProviderDisconnectError."""
        self._disconnect_after_n = n
        return self

    @property
    def request_count(self) -> int:
        """Number of async calls observed so far (useful in assertions)."""
        return self._request_count

    # -- dynamic dispatch --------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._provider, name)
        if not callable(attr) or not inspect.iscoroutinefunction(attr):
            return attr
        return self._make_async_wrapper(attr)

    def _make_async_wrapper(self, func: Any) -> Any:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            self._request_count += 1
            path = args[0] if args else kwargs.get("path")

            if self._fail_after_n is not None:
                threshold, exc = self._fail_after_n
                if self._request_count > threshold:
                    raise exc
            if (
                self._rate_limit_after_n is not None
                and self._request_count > self._rate_limit_after_n
            ):
                raise ProviderRateLimitError(
                    f"rate limited after {self._rate_limit_after_n} requests"
                )
            if (
                self._disconnect_after_n is not None
                and self._request_count > self._disconnect_after_n
            ):
                raise ProviderDisconnectError(
                    f"disconnected after {self._disconnect_after_n} requests"
                )

            if path is not None:
                if path in self._fail_paths:
                    raise self._fail_paths[path]
                if path in self._delay_paths:
                    await asyncio.sleep(self._delay_paths[path])
                if path in self._malformed_paths:
                    return _MALFORMED_SENTINEL
                if path in self._empty_paths:
                    return []

            return await func(*args, **kwargs)

        return wrapper


__all__ = [
    "FaultInjector",
    "ProviderDisconnectError",
    "ProviderRateLimitError",
]
