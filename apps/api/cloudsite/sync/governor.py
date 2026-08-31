import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass(slots=True)
class SyncRequestGovernor:
    target_count: int
    preferred_window_seconds: float = 3600.0
    max_window_seconds: float = 7200.0
    default_min_delay_seconds: float = 5.0
    default_max_delay_seconds: float = 15.0
    absolute_max_rps: float = 2.0
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    random_uniform: Callable[[float, float], float] = random.uniform
    started_at: float = field(init=False)
    completed_count: int = 0
    request_count: int = 0
    response_samples: int = 0
    average_response_seconds: float = 0.0
    budget_wait_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    @property
    def absolute_min_interval(self) -> float:
        return 1.0 / max(0.01, self.absolute_max_rps)

    @property
    def remaining_count(self) -> int:
        return max(0, self.target_count - self.completed_count)

    def delay_range(self) -> tuple[float, float]:
        remaining = max(1, self.remaining_count)
        elapsed = max(0.0, self.clock() - self.started_at)
        available = max(0.0, self.max_window_seconds - elapsed)
        allowed_average = max(
            self.absolute_min_interval,
            available / remaining - self.average_response_seconds,
        )
        default_average = (self.default_min_delay_seconds + self.default_max_delay_seconds) / 2
        if default_average <= allowed_average:
            return self.default_min_delay_seconds, self.default_max_delay_seconds
        low = max(self.absolute_min_interval, allowed_average * 0.75)
        high = max(low, min(self.default_max_delay_seconds, allowed_average * 1.25))
        return low, high

    async def wait_before_request(self) -> float:
        if self.request_count == 0:
            self.request_count += 1
            return 0.0
        low, high = self.delay_range()
        delay = max(self.absolute_min_interval, self.random_uniform(low, high))
        await self.sleeper(delay)
        self.budget_wait_seconds += delay
        self.request_count += 1
        return delay

    def observe_response(self, duration_seconds: float, completed: bool = True) -> None:
        sample = max(0.0, duration_seconds)
        seen = self.response_samples
        self.average_response_seconds = (
            (self.average_response_seconds * seen + sample) / (seen + 1)
        )
        self.response_samples += 1
        if completed:
            self.completed_count += 1

    def mark_completed(self) -> None:
        self.completed_count += 1
