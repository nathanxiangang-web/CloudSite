"""Transactional service for durable A1 parser candidate tasks."""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ParserCandidateTask, utcnow
from ....services.resource_name_parser import ParseResult

TASK_ID_PREFIX = "pt_"
DEFAULT_MAX_RETRIES = 3

_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "failed": {"pending", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class ParserCandidateError(Exception):
    pass


class ParserCandidateNotFound(ParserCandidateError):
    pass


class ParserCandidateTransitionInvalid(ParserCandidateError):
    pass


def _new_task_id() -> str:
    return TASK_ID_PREFIX + secrets.token_hex(16)


async def enqueue_parser_candidate(
    state: AsyncSession,
    *,
    resource_id: str,
    input_fingerprint: str,
    parser_version: str,
    task_id: str | None = None,
) -> tuple[ParserCandidateTask, bool]:
    values = (resource_id.strip(), input_fingerprint.strip(), parser_version.strip())
    if not all(values):
        raise ParserCandidateError("resource, fingerprint, and parser version are required")
    existing = await state.scalar(
        select(ParserCandidateTask).where(
            ParserCandidateTask.resource_id == values[0],
            ParserCandidateTask.input_fingerprint == values[1],
            ParserCandidateTask.parser_version == values[2],
        )
    )
    if existing is not None:
        return existing, False
    row = ParserCandidateTask(
        task_id=task_id or _new_task_id(),
        resource_id=values[0],
        input_fingerprint=values[1],
        parser_version=values[2],
        status="pending",
    )
    state.add(row)
    await state.flush()
    return row, True


async def get_parser_candidate(state: AsyncSession, task_id: str) -> ParserCandidateTask:
    row = await state.get(ParserCandidateTask, task_id)
    if row is None:
        raise ParserCandidateNotFound(task_id)
    return row


async def _transition(
    state: AsyncSession,
    row: ParserCandidateTask,
    target: str,
) -> ParserCandidateTask:
    if target not in _TRANSITIONS.get(row.status, set()):
        raise ParserCandidateTransitionInvalid(f"{row.status} -> {target}")
    row.status = target
    row.updated_at = utcnow()
    await state.flush()
    return row


async def claim_parser_candidate(state: AsyncSession, task_id: str) -> ParserCandidateTask:
    return await _transition(state, await get_parser_candidate(state, task_id), "running")


async def complete_parser_candidate(
    state: AsyncSession,
    task_id: str,
    result: ParseResult,
) -> ParserCandidateTask:
    row = await get_parser_candidate(state, task_id)
    if result.resource_id != row.resource_id or result.parser_version != row.parser_version:
        raise ParserCandidateError("parser result identity does not match candidate task")
    await _transition(state, row, "completed")
    row.result_json = json.dumps(
        asdict(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    row.error_text = None
    row.completed_at = utcnow()
    await state.flush()
    return row


async def fail_parser_candidate(
    state: AsyncSession,
    task_id: str,
    error: str,
) -> ParserCandidateTask:
    row = await _transition(state, await get_parser_candidate(state, task_id), "failed")
    row.error_text = (error.strip() or "parser failed")[:2000]
    row.result_json = None
    row.completed_at = None
    await state.flush()
    return row


async def retry_parser_candidate(
    state: AsyncSession,
    task_id: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> ParserCandidateTask:
    row = await get_parser_candidate(state, task_id)
    if row.retry_count >= max_retries:
        raise ParserCandidateTransitionInvalid("parser retry limit reached")
    await _transition(state, row, "pending")
    row.retry_count += 1
    row.error_text = None
    await state.flush()
    return row


async def cancel_parser_candidate(
    state: AsyncSession,
    task_id: str,
) -> ParserCandidateTask:
    return await _transition(state, await get_parser_candidate(state, task_id), "cancelled")
