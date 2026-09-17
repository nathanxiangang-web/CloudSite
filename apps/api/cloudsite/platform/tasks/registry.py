from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from .domain import Task


class TaskHandler(Protocol):
    async def __call__(self, task: Task) -> dict[str, Any] | None: ...


class TaskTypeRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        self._queues: dict[str, set[str]] = {}

    def register(
        self,
        task_type: str,
        handler: TaskHandler,
        *,
        queue: str = 'default',
    ) -> None:
        if task_type in self._handlers:
            raise ValueError(f'Task type already registered: {task_type}')
        self._handlers[task_type] = handler
        self._queues.setdefault(queue, set()).add(task_type)

    def unregister(self, task_type: str) -> None:
        self._handlers.pop(task_type, None)
        for types in self._queues.values():
            types.discard(task_type)

    def get_handler(self, task_type: str) -> TaskHandler:
        handler = self._handlers.get(task_type)
        if handler is None:
            raise KeyError(f'No handler registered for task type: {task_type}')
        return handler

    def has_handler(self, task_type: str) -> bool:
        return task_type in self._handlers

    def get_types_for_queue(self, queue: str) -> set[str]:
        return self._queues.get(queue, set())

    @property
    def registered_types(self) -> set[str]:
        return set(self._handlers.keys())

    @property
    def count(self) -> int:
        return len(self._handlers)


_registry = TaskTypeRegistry()


def get_registry() -> TaskTypeRegistry:
    return _registry


__all__ = ['TaskHandler', 'TaskTypeRegistry', 'get_registry']
