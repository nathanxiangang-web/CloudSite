from __future__ import annotations


class TaskError(Exception):
    pass


class RetryableError(TaskError):
    pass


class PermanentError(TaskError):
    pass


class RateLimitError(RetryableError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class DependencyError(RetryableError):
    pass


class TaskCancelledError(TaskError):
    pass


class TaskNotFoundError(TaskError):
    pass


class LeaseExpiredError(TaskError):
    pass


class TaskAlreadyExistsError(TaskError):
    pass


__all__ = [
    'TaskError',
    'RetryableError',
    'PermanentError',
    'RateLimitError',
    'DependencyError',
    'TaskCancelledError',
    'TaskNotFoundError',
    'LeaseExpiredError',
    'TaskAlreadyExistsError',
]
