from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .errors import TaskCancelledError, TaskError


class TaskStatus(str, Enum):
    PENDING = 'pending'
    LEASED = 'leased'
    RUNNING = 'running'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    RETRY_WAIT = 'retry_wait'
    CANCELLED = 'cancelled'
    BLOCKED = 'blocked'


class TaskPriority(int, Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 10
    URGENT = 20


_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.LEASED, TaskStatus.CANCELLED, TaskStatus.BLOCKED},
    TaskStatus.LEASED: {TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.RETRY_WAIT,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RETRY_WAIT: {TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.PENDING, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: {TaskStatus.PENDING},
    TaskStatus.CANCELLED: set(),
}

TERMINAL_STATUSES = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
ACTIVE_STATUSES = {TaskStatus.PENDING, TaskStatus.LEASED, TaskStatus.RUNNING, TaskStatus.RETRY_WAIT, TaskStatus.BLOCKED}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Task:
    """Task domain entity with state machine validation."""

    def __init__(
        self,
        task_id: str,
        task_type: str,
        queue: str = 'default',
        status: TaskStatus = TaskStatus.PENDING,
        priority: TaskPriority = TaskPriority.NORMAL,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        max_attempts: int = 5,
        attempt_count: int = 0,
        created_at: datetime | None = None,
        scheduled_at: datetime | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
        retry_at: datetime | None = None,
        last_error_code: str | None = None,
        last_error_message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.queue = queue
        self.status = status
        self.priority = priority
        self.payload = payload or {}
        self.dedupe_key = dedupe_key
        self.parent_task_id = parent_task_id
        self.root_task_id = root_task_id or task_id
        self.max_attempts = max_attempts
        self.attempt_count = attempt_count
        self.created_at = created_at or _utcnow()
        self.scheduled_at = scheduled_at or self.created_at
        self.started_at = started_at
        self.finished_at = finished_at
        self.lease_owner = lease_owner
        self.lease_expires_at = lease_expires_at
        self.retry_at = retry_at
        self.last_error_code = last_error_code
        self.last_error_message = last_error_message
        self.result = result

    def _transition(self, new_status: TaskStatus) -> None:
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise TaskError(
                f'Invalid transition: {self.status.value} -> {new_status.value}'
            )
        self.status = new_status

    def lease(self, owner: str, expires_at: datetime) -> None:
        self._transition(TaskStatus.LEASED)
        self.lease_owner = owner
        self.lease_expires_at = expires_at

    def start(self) -> None:
        self._transition(TaskStatus.RUNNING)
        self.started_at = _utcnow()
        self.attempt_count += 1

    def succeed(self, result: dict[str, Any] | None = None) -> None:
        self._transition(TaskStatus.SUCCEEDED)
        self.finished_at = _utcnow()
        self.result = result
        self.lease_owner = None
        self.lease_expires_at = None

    def fail(self, error_code: str, error_message: str) -> None:
        self._transition(TaskStatus.FAILED)
        self.finished_at = _utcnow()
        self.last_error_code = error_code
        self.last_error_message = error_message
        self.lease_owner = None
        self.lease_expires_at = None

    def schedule_retry(self, retry_at: datetime, error_code: str, error_message: str) -> None:
        self._transition(TaskStatus.RETRY_WAIT)
        self.retry_at = retry_at
        self.last_error_code = error_code
        self.last_error_message = error_message
        self.lease_owner = None
        self.lease_expires_at = None

    def requeue(self) -> None:
        self._transition(TaskStatus.PENDING)
        self.retry_at = None
        self.lease_owner = None
        self.lease_expires_at = None

    def cancel(self) -> None:
        if self.status in TERMINAL_STATUSES:
            raise TaskCancelledError(f'Cannot cancel task in terminal status: {self.status.value}')
        self._transition(TaskStatus.CANCELLED)
        self.finished_at = _utcnow()
        self.lease_owner = None
        self.lease_expires_at = None

    def block(self) -> None:
        self._transition(TaskStatus.BLOCKED)

    def unblock(self) -> None:
        self._transition(TaskStatus.PENDING)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_lease_expired(self) -> bool:
        if self.lease_expires_at is None:
            return False
        return _utcnow() > self.lease_expires_at

    @property
    def can_retry(self) -> bool:
        return self.attempt_count < self.max_attempts


__all__ = [
    'TaskStatus',
    'TaskPriority',
    'Task',
    'TERMINAL_STATUSES',
    'ACTIVE_STATUSES',
]
