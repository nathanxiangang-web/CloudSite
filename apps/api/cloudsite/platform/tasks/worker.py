from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any

from ..db.session import state_session
from .domain import Task, TaskStatus
from .errors import (
    DependencyError,
    PermanentError,
    RateLimitError,
    RetryableError,
    TaskCancelledError,
    TaskError,
)
from .lease import DEFAULT_LEASE_TTL, HEARTBEAT_INTERVAL, generate_lease_owner, renew_lease
from .registry import TaskTypeRegistry, get_registry
from .repository import TaskRepository
from .retry import default_retry_policy

logger = logging.getLogger(__name__)


class Worker:
    """Async worker that leases and executes tasks.

    Independent of FastAPI. Uses DB-backed queue with lease + retry.
    Supports graceful shutdown via SIGINT/SIGTERM.
    """

    def __init__(
        self,
        queue: str = 'default',
        *,
        owner: str | None = None,
        registry: TaskTypeRegistry | None = None,
        poll_interval: float = 2.0,
        lease_ttl: Any = DEFAULT_LEASE_TTL,
        max_concurrent: int = 4,
    ) -> None:
        self.queue = queue
        self.owner = owner or generate_lease_owner()
        self._registry = registry or get_registry()
        self._poll_interval = poll_interval
        self._lease_ttl = lease_ttl
        self._max_concurrent = max_concurrent
        self._running = False
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self._running = True
        logger.info('Worker %s starting for queue=%s', self.owner, self.queue)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_signal)
            except NotImplementedError:
                pass
        try:
            await self._run_loop()
        finally:
            await self._drain()

    async def stop(self) -> None:
        self._running = False

    def _handle_signal(self) -> None:
        logger.info('Worker %s received shutdown signal', self.owner)
        self._running = False

    async def _run_loop(self) -> None:
        while self._running:
            try:
                leased = await self._try_lease_one()
                if leased is not None:
                    task = asyncio.create_task(self._execute(leased))
                    self._active_tasks[leased.task_id] = task
                else:
                    await asyncio.sleep(self._poll_interval)
            except Exception:
                logger.exception('Worker loop error')
                await asyncio.sleep(self._poll_interval)
            self._reap()

    async def _try_lease_one(self) -> Task | None:
        async with state_session() as session:
            repo = TaskRepository(session)
            task = await repo.lease_next(self.queue, owner=self.owner, ttl=self._lease_ttl)
            if task is not None:
                await session.commit()
            return task

    async def _execute(self, task: Task) -> None:
        async with self._semaphore:
            try:
                await self._run_task(task)
            except Exception:
                logger.exception('Unhandled error executing task %s', task.task_id)
            finally:
                self._active_tasks.pop(task.task_id, None)

    async def _run_task(self, task: Task) -> None:
        handler = self._registry.get_handler(task.task_type)
        async with state_session() as session:
            repo = TaskRepository(session)
            try:
                fetched = await repo.get(task.task_id)
                fetched.start()
                await repo.save(fetched)
                await session.commit()
            except Exception:
                logger.exception('Failed to mark task %s as running', task.task_id)
                return

            heartbeat = asyncio.create_task(self._heartbeat(task.task_id))

            try:
                result = await handler(fetched)
                fetched.succeed(result)
                await repo.save(fetched)
                await session.commit()
                logger.info('Task %s succeeded', task.task_id)
            except TaskCancelledError:
                fetched.cancel()
                await repo.save(fetched)
                await session.commit()
                logger.info('Task %s cancelled', task.task_id)
            except PermanentError as e:
                fetched.fail('PERMANENT', str(e))
                await repo.save(fetched)
                await session.commit()
                logger.warning('Task %s failed permanently: %s', task.task_id, e)
            except RateLimitError as e:
                await self._handle_retry(fetched, repo, session, 'RATE_LIMIT', str(e), retry_after=e.retry_after)
            except RetryableError as e:
                await self._handle_retry(fetched, repo, session, 'RETRYABLE', str(e))
            except DependencyError as e:
                await self._handle_retry(fetched, repo, session, 'DEPENDENCY', str(e))
            except Exception as e:
                await self._handle_retry(fetched, repo, session, 'UNEXPECTED', str(e))
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass

    async def _handle_retry(
        self,
        task: Task,
        repo: TaskRepository,
        session: Any,
        error_code: str,
        error_message: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        if not task.can_retry:
            task.fail(error_code, error_message)
            await repo.save(task)
            await session.commit()
            logger.warning('Task %s exhausted retries (%s): %s', task.task_id, error_code, error_message)
            return

        if retry_after is not None:
            from datetime import timedelta
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_after)
        else:
            retry_at = default_retry_policy.get_retry_at(task.attempt_count)

        task.schedule_retry(retry_at, error_code, error_message)
        await repo.save(task)
        await session.commit()
        logger.info('Task %s scheduled retry at %s (%s)', task.task_id, retry_at, error_code)

    async def _heartbeat(self, task_id: str) -> None:
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL.total_seconds())
            try:
                async with state_session() as session:
                    repo = TaskRepository(session)
                    await repo.renew_lease(task_id, self.owner, self._lease_ttl)
                    await session.commit()
            except Exception:
                logger.warning('Heartbeat failed for task %s', task_id)

    def _reap(self) -> None:
        done = [tid for tid, t in self._active_tasks.items() if t.done()]
        for tid in done:
            self._active_tasks.pop(tid, None)

    async def _drain(self) -> None:
        logger.info('Worker %s draining %d active tasks', self.owner, len(self._active_tasks))
        for task in self._active_tasks.values():
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        self._active_tasks.clear()
        logger.info('Worker %s stopped', self.owner)


__all__ = ['Worker']