"""Catalog revision write-side helpers."""

from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import CatalogRevision


REVISION_ID_PREFIX = "cv_"
_ID_HEX_LEN = 32
_REVISION_TARGET_TYPES = {
    "entry",
    "release",
    "asset",
    "location",
    "tag",
    "relation",
}
_REVISION_ACTIONS = {
    "create",
    "update",
    "delete",
    "publish",
    "unpublish",
    "archive",
    "disable",
}


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


def _json(value: dict[str, Any] | None) -> str:
    return json.dumps(
        value or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class CatalogRevisionInvalid(ValueError):
    pass


async def append_catalog_revision(
    state: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    action: str,
    actor: str,
    source: str = "admin",
    base_revision: int | None = None,
    resulting_revision: int | None = None,
    summary: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    diff: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    revision_id: str | None = None,
) -> CatalogRevision:
    if target_type not in _REVISION_TARGET_TYPES:
        raise CatalogRevisionInvalid(
            f"unsupported revision target type: {target_type}"
        )
    if action not in _REVISION_ACTIONS:
        raise CatalogRevisionInvalid(
            f"unsupported revision action: {action}"
        )
    if not actor.strip():
        raise CatalogRevisionInvalid("revision actor is required")
    row = CatalogRevision(
        revision_id=revision_id or _new_id(REVISION_ID_PREFIX),
        target_type=target_type,
        target_id=target_id,
        action=action,
        actor=actor.strip(),
        source=source.strip() or "admin",
        base_revision=base_revision,
        resulting_revision=resulting_revision,
        summary=summary,
        before_json=_json(before),
        after_json=_json(after),
        diff_json=_json(diff),
        payload_json=_json(payload),
    )
    state.add(row)
    await state.flush()
    return row


__all__ = ["CatalogRevisionInvalid", "append_catalog_revision"]
