"""Bounded execution adapter for one durable parser candidate task."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ...resources.contracts.public import ParserResourceView, resource_queries
from ..domain.resource_name_parser import PARSER_VERSION, ParseResult, parse_resource_name
from ..infrastructure.models import ParserCandidateTask
from .parser_candidates import (
    claim_parser_candidate,
    complete_parser_candidate,
    fail_parser_candidate,
)


@dataclass(frozen=True)
class ParserCandidateRunResult:
    task: ParserCandidateTask
    result: ParseResult | None
    error: str | None


def parser_input_fingerprint(resource: ParserResourceView) -> str:
    """Fingerprint only the indexed fields consumed by the deterministic parser."""

    value = json.dumps(
        {
            "resource_id": resource.id,
            "name": resource.name,
            "path": resource.path,
            "extension": resource.extension,
            "mime_type": resource.mime_type,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def run_parser_candidate(
    state: AsyncSession,
    index: AsyncSession,
    task_id: str,
) -> ParserCandidateRunResult:
    """Claim and finish one task without committing either database session.

    Expected input problems become a durable failed task rather than escaping
    and blocking the caller's work loop. Invalid task transitions still raise
    from ``claim_parser_candidate`` so two runners cannot both claim one row.
    """

    task = await claim_parser_candidate(state, task_id)
    error: str | None = None
    resource: ParserResourceView | None = None

    if task.parser_version != PARSER_VERSION:
        error = f"unsupported parser version: {task.parser_version}"
    else:
        resource = await resource_queries(index).parser_resource(resource_id=task.resource_id)
        if resource is None or resource.status != "active":
            error = "parser input resource is unavailable"
        elif parser_input_fingerprint(resource) != task.input_fingerprint:
            error = "parser input fingerprint is stale"

    if error is not None:
        failed = await fail_parser_candidate(state, task.task_id, error)
        return ParserCandidateRunResult(task=failed, result=None, error=error)

    assert resource is not None
    result = parse_resource_name(
        resource.id,
        resource.name,
        resource.path,
        resource.extension,
        resource.mime_type,
    )
    completed = await complete_parser_candidate(state, task.task_id, result)
    return ParserCandidateRunResult(task=completed, result=result, error=None)
