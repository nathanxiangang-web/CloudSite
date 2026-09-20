from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import StateBase
from .domain import Task, TaskPriority, TaskStatus
from .errors import TaskAlreadyExistsError, TaskNotFoundError
from .lease import DEFAULT_LEASE_TTL, compute_lease_expiry, generate_lease_owner, is_expired
from .models import TaskORM


def _generate_task_id(prefix: str = 'task') -> str:
    return f'{prefix}_{secrets.token_hex(16)}'


def _orm_to_domain(orm: TaskORM) -> Task:
    return Task(
        task_id=orm.task_id,
        task_type=orm.task_type,
        queue=orm.queue,
        status=TaskStatus(orm.status),
        priority=TaskPriority(orm.priority),
        payload=orm.payload,
        dedupe_key=orm.dedupe_key,
        parent_task_id=orm.parent_task_id,
        root_task_id=orm.root_task_id,
        max_attempts=orm.max_attempts,
        attempt_count=orm.attempt_count,
        created_at=orm.created_at,
        scheduled_at=orm.scheduled_at,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
        lease_owner=orm.lease_owner,
        lease_expires_at=orm.lease_expires_at,
        retry_at=orm.retry_at,
        last_error_code=orm.last_error_code,
        last_error_message=orm.last_error_message,
        result=orm.result,
    )


def _domain_to_orm(task: Task, orm: TaskORM | None = None) -> TaskORM:
    if orm is None:
        orm = TaskORM(
            task_id=task.task_id,
            task_type=task.task_type,
            queue=task.queue,
            root_task_id=task.root_task_id,
            created_at=task.created_at,
            scheduled_at=task.scheduled_at,
        )
    orm.status = task.status.value
    orm.priority = task.priority.value
    orm.payload = task.payload
    orm.dedupe_key = task.dedupe_key
    orm.parent_task_id = task.parent_task_id
    orm.max_attempts = task.max_attempts
    orm.attempt_count = task.attempt_count
    orm.started_at = task.started_at
    orm.finished_at = task.finished_at
    orm.lease_owner = task.lease_owner
    orm.lease_expires_at = task.lease_expires_at
    orm.retry_at = task.retry_at
    orm.last_error_code = task.last_error_code
    orm.last_error_message = task.last_error_message
    orm.result = task.result
    return orm


class TaskRepository:
    """DB-backed task repository with lease, dedupe, and priority support."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        if task.dedupe_key:
            stmt = select(TaskORM).where(
                TaskORM.dedupe_key == task.dedupe_key,
                TaskORM.status.in_([
                    TaskStatus.PENDING.value,
                    TaskStatus.LEASED.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.RETRY_WAIT.value,
                    TaskStatus.BLOCKED.value,
                ]),
            )
            existing = await self._session.execute(stmt)
            if existing.scalar_one_or_none() is not None:
                raise TaskAlreadyExistsError(
                    f'Active task with dedupe_key={task.dedupe_key!r} already exists'
                )
        orm = _domain_to_orm(task)
        self._session.add(orm)
        await self._session.flush()
        return task

    async def get(self, task_id: str) -> Task:
        orm = await self._session.get(TaskORM, task_id)
        if orm is None:
            raise TaskNotFoundError(f'Task not found: {task_id}')
        return _orm_to_domain(orm)

    async def list(
        self,
        *,
        queue: str | None = None,
        status: TaskStatus | None = None,
        task_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Task]:
        stmt = select(TaskORM)
        if queue is not None:
            stmt = stmt.where(TaskORM.queue == queue)
        if status is not None:
            stmt = stmt.where(TaskORM.status == status.value)
        if task_type is not None:
            stmt = stmt.where(TaskORM.task_type == task_type)
        stmt = stmt.order_by(TaskORM.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return [_orm_to_domain(orm) for orm in result.scalars().all()]

    async def save(self, task: Task) -> Task:
        orm = await self._session.get(TaskORM, task.task_id)
        if orm is None:
            raise TaskNotFoundError(f'Task not found: {task.task_id}')
        _domain_to_orm(task, orm)
        await self._session.flush()
        return task

    async def lease_next(
        self,
        queue: str = 'default',
        *,
        owner: str | None = None,
        ttl: timedelta = DEFAULT_LEASE_TTL,
    ) -> Task | None:
        now = datetime.now(timezone.utc)
        lease_owner = owner or generate_lease_owner()
        expires_at = compute_lease_expiry(ttl, now=now)

        expired_stmt = (
            update(TaskORM)
            .where(
                TaskORM.queue == queue,
                TaskORM.status == TaskStatus.LEASED.value,
                TaskORM.lease_expires_at < now,
            )
            .values(
                status=TaskStatus.PENDING.value,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        await self._session.execute(expired_stmt)

        retry_stmt = (
            update(TaskORM)
            .where(
                TaskORM.queue == queue,
                TaskORM.status == TaskStatus.RETRY_WAIT.value,
                TaskORM.retry_at <= now,
            )
            .values(
                status=TaskStatus.PENDING.value,
                retry_at=None,
            )
        )
        await self._session.execute(retry_stmt)

        stmt = (
            select(TaskORM)
            .where(
                TaskORM.queue == queue,
                TaskORM.status == TaskStatus.PENDING.value,
            )
            .order_by(TaskORM.priority.desc(), TaskORM.scheduled_at.asc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None

        task = _orm_to_domain(orm)
        task.lease(lease_owner, expires_at)
        _domain_to_orm(task, orm)
        await self._session.flush()
        return task

    async def renew_lease(self, task_id: str, owner: str, ttl: timedelta = DEFAULT_LEASE_TTL) -> Task:
        task = await self.get(task_id)
        if task.lease_owner != owner:
            raise TaskNotFoundError(f'Lease owner mismatch for task: {task_id}')
        if is_expired(task.lease_expires_at):
            from .errors import LeaseExpiredError
            raise LeaseExpiredError(f'Lease expired for task: {task_id}')
        task.lease_expires_at = compute_lease_expiry(ttl)
        return await self.save(task)

    async def count(self, *, status: TaskStatus | None = None, queue: str | None = None) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(TaskORM)
        if status is not None:
            stmt = stmt.where(TaskORM.status == status.value)
        if queue is not None:
            stmt = stmt.where(TaskORM.queue == queue)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def cancel(self, task_id: str) -> Task:
        task = await self.get(task_id)
        task.cancel()
        return await self.save(task)


__all__ = ['TaskRepository', '_generate_task_id']
