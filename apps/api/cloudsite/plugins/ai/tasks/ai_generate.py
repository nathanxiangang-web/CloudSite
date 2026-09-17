"""AI generate draft task handler.

Registered as 'ai.generate_draft' in the platform task registry.
When a task is leased by a Worker, this handler:
1. Calls the AI provider to generate content (placeholder for now)
2. Persists the draft via ai_completion.generate_draft
3. Maps BudgetExceeded to RateLimitError for next-day retry
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cloudsite.platform.tasks.domain import Task
from cloudsite.platform.tasks.errors import PermanentError, RateLimitError
from cloudsite.plugins.ai.services.ai_completion import (
    BudgetExceeded,
    NoEnabledProvider,
    generate_draft,
)


def _seconds_until_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - now).total_seconds()))


async def handle_ai_generate_draft(task: Task) -> dict:
    """Task handler for ai.generate_draft.

    Payload keys:
        target_entry_id: str
        field_type: str
        config_id: str | None
        generated_content: str | None  (if pre-computed)
        tokens_used: int | None
        elapsed_ms: int | None
    """
    p = task.payload
    target_entry_id = p["target_entry_id"]
    field_type = p["field_type"]
    config_id = p.get("config_id")
    generated_content = p.get("generated_content", "")
    tokens_used = p.get("tokens_used", 0)
    elapsed_ms = p.get("elapsed_ms", 0)

    from cloudsite.database import StateSession

    try:
        async with StateSession() as state:
            result = await generate_draft(
                state,
                target_entry_id=target_entry_id,
                field_type=field_type,
                config_id=config_id,
                generated_content=generated_content,
                tokens_used=tokens_used,
                elapsed_ms=elapsed_ms,
            )
            await state.commit()
            return {"draft_id": result.draft_id, "status": result.status}
    except BudgetExceeded as exc:
        raise RateLimitError(str(exc), retry_after=_seconds_until_midnight_utc()) from exc
    except NoEnabledProvider as exc:
        raise PermanentError(str(exc)) from exc


__all__ = ["handle_ai_generate_draft"]