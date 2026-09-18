from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import StateSession
from ..db.session import state_session
from .domain import Task, TaskPriority, TaskStatus, ACTIVE_STATUSES, TERMINAL_STATUSES
from .errors import TaskNotFoundError, TaskAlreadyExistsError, LeaseExpiredError
from .repository import TaskRepository, _generate_task_id

router = APIRouter(prefix="/api/admin/tasks", tags=["admin-tasks"])


class TaskCreateRequest(BaseModel):
    task_type: str
    queue: str = "default"
    priority: int = 5
    payload: dict[str, Any] | None = None
    dedupe_key: str | None = None
    parent_task_id: str | None = None
    max_attempts: int = 5


class TaskResponse(BaseModel):
    task_id: str
    task_type: str
    queue: str
    status: str
    priority: int
    payload: dict[str, Any] | None = None
    dedupe_key: str | None = None
    parent_task_id: str | None = None
    root_task_id: str
    max_attempts: int
    attempt_count: int
    created_at: datetime
    scheduled_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    retry_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    result: dict[str, Any] | None = None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int


def _task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        task_id=task.task_id,
        task_type=task.task_type,
        queue=task.queue,
        status=task.status.value,
        priority=task.priority.value,
        payload=task.payload,
        dedupe_key=task.dedupe_key,
        parent_task_id=task.parent_task_id,
        root_task_id=task.root_task_id,
        max_attempts=task.max_attempts,
        attempt_count=task.attempt_count,
        created_at=task.created_at,
        scheduled_at=task.scheduled_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        lease_owner=task.lease_owner,
        lease_expires_at=task.lease_expires_at,
        retry_at=task.retry_at,
        last_error_code=task.last_error_code,
        last_error_message=task.last_error_message,
        result=task.result,
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    queue: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    status_enum = TaskStatus(status) if status else None
    async with state_session() as session:
        repo = TaskRepository(session)
        tasks = await repo.list(
            queue=queue, status=status_enum, task_type=task_type,
            offset=offset, limit=limit,
        )
        total = await repo.count(status=status_enum, queue=queue)
    return TaskListResponse(items=[_task_to_response(t) for t in tasks], total=total)


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(req: TaskCreateRequest):
    now = datetime.now(timezone.utc)
    task = Task(
        task_id=_generate_task_id(),
        task_type=req.task_type,
        queue=req.queue,
        priority=TaskPriority(req.priority),
        payload=req.payload,
        dedupe_key=req.dedupe_key,
        parent_task_id=req.parent_task_id,
        max_attempts=req.max_attempts,
        created_at=now,
        scheduled_at=now,
    )
    async with state_session() as session:
        repo = TaskRepository(session)
        try:
            await repo.create(task)
            await session.commit()
        except TaskAlreadyExistsError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return _task_to_response(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    async with state_session() as session:
        repo = TaskRepository(session)
        try:
            task = await repo.get(task_id)
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return _task_to_response(task)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str):
    async with state_session() as session:
        repo = TaskRepository(session)
        try:
            task = await repo.cancel(task_id)
            await session.commit()
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e))
    return _task_to_response(task)


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(task_id: str):
    async with state_session() as session:
        repo = TaskRepository(session)
        try:
            task = await repo.get(task_id)
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        if task.status not in (TaskStatus.FAILED, TaskStatus.RETRY_WAIT):
            raise HTTPException(status_code=409, detail=f"Cannot retry task in status: {task.status.value}")
        task.requeue()
        await repo.save(task)
        await session.commit()
    return _task_to_response(task)