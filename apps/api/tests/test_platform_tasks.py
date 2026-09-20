"""Unit tests for platform/tasks: state machine, lease, retry, dedupe, repository."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.platform.tasks.domain import (
    Task, TaskStatus, TaskPriority,
    TERMINAL_STATUSES, ACTIVE_STATUSES,
)
from cloudsite.platform.tasks.errors import (
    TaskError, RetryableError, PermanentError, RateLimitError,
    TaskCancelledError, TaskAlreadyExistsError, LeaseExpiredError,
)
from cloudsite.platform.tasks.lease import (
    generate_lease_owner, compute_lease_expiry, is_expired, renew_lease,
    DEFAULT_LEASE_TTL,
)
from cloudsite.platform.tasks.retry import RetryPolicy, default_retry_policy
from cloudsite.platform.tasks.registry import TaskTypeRegistry
from cloudsite.platform.tasks.repository import TaskRepository, _generate_task_id
from cloudsite.platform.tasks.models import TaskORM
from cloudsite.platform.db.base import StateBase


# ─── State Machine Tests ───

class TestTaskStateMachine:
    def test_initial_status_is_pending(self):
        t = Task(task_id="t1", task_type="test")
        assert t.status == TaskStatus.PENDING

    def test_pending_to_leased(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        assert t.status == TaskStatus.LEASED
        assert t.lease_owner == "w1"

    def test_leased_to_running(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        assert t.status == TaskStatus.RUNNING
        assert t.attempt_count == 1
        assert t.started_at is not None

    def test_running_to_succeeded(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        t.succeed({"key": "value"})
        assert t.status == TaskStatus.SUCCEEDED
        assert t.is_terminal
        assert t.result == {"key": "value"}
        assert t.finished_at is not None

    def test_running_to_failed(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        t.fail("ERR", "something broke")
        assert t.status == TaskStatus.FAILED
        assert t.last_error_code == "ERR"

    def test_running_to_retry_wait(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        t.schedule_retry(retry_at, "RETRY", "transient")
        assert t.status == TaskStatus.RETRY_WAIT
        assert t.retry_at == retry_at

    def test_retry_wait_to_pending(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        t.schedule_retry(datetime.now(timezone.utc), "RETRY", "transient")
        t.requeue()
        assert t.status == TaskStatus.PENDING

    def test_cancel_from_pending(self):
        t = Task(task_id="t1", task_type="test")
        t.cancel()
        assert t.status == TaskStatus.CANCELLED
        assert t.is_terminal

    def test_cancel_from_running(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        t.cancel()
        assert t.status == TaskStatus.CANCELLED

    def test_invalid_transition_raises(self):
        t = Task(task_id="t1", task_type="test")
        with pytest.raises(TaskError):
            t.succeed()

    def test_cancel_terminal_raises(self):
        t = Task(task_id="t1", task_type="test")
        t.cancel()
        with pytest.raises(TaskCancelledError):
            t.cancel()

    def test_block_and_unblock(self):
        t = Task(task_id="t1", task_type="test")
        t.block()
        assert t.status == TaskStatus.BLOCKED
        t.unblock()
        assert t.status == TaskStatus.PENDING

    def test_can_retry_property(self):
        t = Task(task_id="t1", task_type="test", max_attempts=3)
        assert t.can_retry
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        assert t.can_retry
        t.schedule_retry(datetime.now(timezone.utc), "R", "x")
        t.requeue()
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        t.schedule_retry(datetime.now(timezone.utc), "R", "x")
        t.requeue()
        t.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        t.start()
        assert not t.can_retry

    def test_lease_expired_property(self):
        t = Task(task_id="t1", task_type="test")
        t.lease("w1", datetime.now(timezone.utc) - timedelta(minutes=1))
        assert t.is_lease_expired
        t2 = Task(task_id="t2", task_type="test")
        t2.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        assert not t2.is_lease_expired


# ─── Lease Tests ───

class TestLease:
    def test_generate_lease_owner(self):
        owner = generate_lease_owner()
        assert owner.startswith("worker-")
        assert len(owner) > 8

    def test_compute_lease_expiry(self):
        now = datetime.now(timezone.utc)
        expiry = compute_lease_expiry(DEFAULT_LEASE_TTL, now=now)
        assert expiry > now

    def test_is_expired(self):
        now = datetime.now(timezone.utc)
        assert is_expired(now - timedelta(minutes=1), now=now)
        assert not is_expired(now + timedelta(minutes=5), now=now)
        assert is_expired(None)

    def test_renew_lease(self):
        now = datetime.now(timezone.utc)
        current = now + timedelta(minutes=2)
        renewed = renew_lease(current, DEFAULT_LEASE_TTL, now=now)
        assert renewed > current


# ─── Retry Policy Tests ───

class TestRetryPolicy:
    def test_default_backoff(self):
        rp = default_retry_policy
        assert rp.get_delay(1) == 0
        assert rp.get_delay(2) == 30
        assert rp.get_delay(3) == 120
        assert rp.get_delay(4) == 600
        assert rp.get_delay(5) == 1800

    def test_custom_backoff(self):
        rp = RetryPolicy(backoff_seconds=[10, 20, 30])
        assert rp.get_delay(1) == 10
        assert rp.get_delay(2) == 20
        assert rp.get_delay(3) == 30
        assert rp.get_delay(4) == 30  # clamped to last

    def test_get_retry_at(self):
        rp = RetryPolicy(backoff_seconds=[60])
        now = datetime.now(timezone.utc)
        retry_at = rp.get_retry_at(1, now=now)
        assert retry_at == now + timedelta(seconds=60)

    def test_should_retry(self):
        rp = default_retry_policy
        assert rp.should_retry(1, 5)
        assert rp.should_retry(4, 5)
        assert not rp.should_retry(5, 5)


# ─── Task Type Registry Tests ───

class TestTaskTypeRegistry:
    def test_register_and_get(self):
        reg = TaskTypeRegistry()
        async def handler(task): return None
        reg.register("test.type", handler)
        assert reg.has_handler("test.type")
        assert reg.get_handler("test.type") is handler

    def test_duplicate_raises(self):
        reg = TaskTypeRegistry()
        async def handler(task): return None
        reg.register("test.type", handler)
        with pytest.raises(ValueError):
            reg.register("test.type", handler)

    def test_unregister(self):
        reg = TaskTypeRegistry()
        async def handler(task): return None
        reg.register("test.type", handler)
        reg.unregister("test.type")
        assert not reg.has_handler("test.type")

    def test_get_types_for_queue(self):
        reg = TaskTypeRegistry()
        async def h1(task): return None
        async def h2(task): return None
        reg.register("type.a", h1, queue="q1")
        reg.register("type.b", h2, queue="q1")
        reg.register("type.c", h2, queue="q2")
        assert reg.get_types_for_queue("q1") == {"type.a", "type.b"}
        assert reg.get_types_for_queue("q2") == {"type.c"}


# ─── Task ID Generation ───

class TestTaskIdGeneration:
    def test_generate_task_id(self):
        tid = _generate_task_id()
        assert tid.startswith("task_")
        assert len(tid) > 10

    def test_generate_task_id_with_prefix(self):
        tid = _generate_task_id("index")
        assert tid.startswith("index_")


# ─── Repository Tests (with in-memory SQLite) ───

@pytest.fixture
async def task_db_session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


class TestTaskRepository:
    @pytest.mark.asyncio
    async def test_create_and_get(self, task_db_session):
        repo = TaskRepository(task_db_session)
        task = Task(
            task_id=_generate_task_id(),
            task_type="test.type",
            payload={"key": "value"},
        )
        await repo.create(task)
        await task_db_session.commit()

        fetched = await repo.get(task.task_id)
        assert fetched.task_type == "test.type"
        assert fetched.payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_dedupe_blocks_duplicate(self, task_db_session):
        repo = TaskRepository(task_db_session)
        t1 = Task(task_id=_generate_task_id(), task_type="test.type", dedupe_key="unique-1")
        await repo.create(t1)
        await task_db_session.commit()

        t2 = Task(task_id=_generate_task_id(), task_type="test.type", dedupe_key="unique-1")
        with pytest.raises(TaskAlreadyExistsError):
            await repo.create(t2)

    @pytest.mark.asyncio
    async def test_lease_next(self, task_db_session):
        repo = TaskRepository(task_db_session)
        task = Task(
            task_id=_generate_task_id(),
            task_type="test.type",
            queue="default",
            priority=TaskPriority.HIGH,
        )
        await repo.create(task)
        await task_db_session.commit()

        leased = await repo.lease_next("default", owner="w1")
        assert leased is not None
        assert leased.status == TaskStatus.LEASED
        assert leased.lease_owner == "w1"

    @pytest.mark.asyncio
    async def test_lease_next_priority_order(self, task_db_session):
        repo = TaskRepository(task_db_session)
        low = Task(task_id=_generate_task_id(), task_type="test", priority=TaskPriority.LOW)
        high = Task(task_id=_generate_task_id(), task_type="test", priority=TaskPriority.HIGH)
        await repo.create(low)
        await repo.create(high)
        await task_db_session.commit()

        leased = await repo.lease_next("default")
        assert leased.priority == TaskPriority.HIGH

    @pytest.mark.asyncio
    async def test_lease_next_empty_queue(self, task_db_session):
        repo = TaskRepository(task_db_session)
        result = await repo.lease_next("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_state_change(self, task_db_session):
        repo = TaskRepository(task_db_session)
        task = Task(task_id=_generate_task_id(), task_type="test.type")
        await repo.create(task)
        await task_db_session.commit()

        task.lease("w1", datetime.now(timezone.utc) + timedelta(minutes=5))
        await repo.save(task)
        await task_db_session.commit()

        fetched = await repo.get(task.task_id)
        assert fetched.status == TaskStatus.LEASED

    @pytest.mark.asyncio
    async def test_cancel_task(self, task_db_session):
        repo = TaskRepository(task_db_session)
        task = Task(task_id=_generate_task_id(), task_type="test.type")
        await repo.create(task)
        await task_db_session.commit()

        cancelled = await repo.cancel(task.task_id)
        assert cancelled.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_list_with_filter(self, task_db_session):
        repo = TaskRepository(task_db_session)
        for i in range(5):
            t = Task(
                task_id=_generate_task_id(),
                task_type="test.type",
                queue="q1" if i < 3 else "q2",
            )
            await repo.create(t)
        await task_db_session.commit()

        q1_tasks = await repo.list(queue="q1")
        assert len(q1_tasks) == 3
        q2_tasks = await repo.list(queue="q2")
        assert len(q2_tasks) == 2

    @pytest.mark.asyncio
    async def test_count(self, task_db_session):
        repo = TaskRepository(task_db_session)
        for _ in range(3):
            t = Task(task_id=_generate_task_id(), task_type="test.type")
            await repo.create(t)
        await task_db_session.commit()

        assert await repo.count() == 3
        assert await repo.count(status=TaskStatus.PENDING) == 3
        assert await repo.count(status=TaskStatus.SUCCEEDED) == 0