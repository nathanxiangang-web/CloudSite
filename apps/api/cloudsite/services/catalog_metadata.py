"""Catalog C3 metadata services: tags, relations, and revision records.

The metadata lives in state.db and never depends on index rebuilds.  Public
relation reads fail closed by returning only relations whose source and target
entries are currently published.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogRelation,
    CatalogRelease,
    CatalogRevision,
    CatalogTag,
    CatalogTagAssignment,
)
from .catalog_search_projection import enqueue_catalog_search_outbox

TAG_ID_PREFIX = "ct_"
RELATION_ID_PREFIX = "cx_"
REVISION_ID_PREFIX = "cv_"
_ID_HEX_LEN = 32
_TAG_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TARGET_MODELS = {
    "entry": CatalogEntry,
    "release": CatalogRelease,
    "asset": CatalogAsset,
}
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
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class CatalogMetadataError(Exception):
    """Base class for metadata service errors."""


class CatalogMetadataNotFound(CatalogMetadataError):
    def __init__(self, object_type: str, object_id: str):
        super().__init__(f"catalog {object_type} not found: {object_id}")
        self.object_type = object_type
        self.object_id = object_id


class CatalogMetadataConflict(CatalogMetadataError):
    pass


class CatalogMetadataInvalid(CatalogMetadataError):
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
    """Append one immutable audit record without committing the transaction."""
    if target_type not in _REVISION_TARGET_TYPES:
        raise CatalogMetadataInvalid(f"unsupported revision target type: {target_type}")
    if action not in _REVISION_ACTIONS:
        raise CatalogMetadataInvalid(f"unsupported revision action: {action}")
    if not actor.strip():
        raise CatalogMetadataInvalid("revision actor is required")
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


async def create_catalog_tag(
    state: AsyncSession,
    *,
    slug: str,
    display_name: str,
    actor: str = "system",
    tag_id: str | None = None,
) -> CatalogTag:
    slug = slug.strip()
    display_name = display_name.strip()
    if not _TAG_SLUG_RE.fullmatch(slug):
        raise CatalogMetadataInvalid("tag slug must be lowercase URL-safe text")
    if not display_name:
        raise CatalogMetadataInvalid("tag display name is required")
    existing = await state.scalar(select(CatalogTag).where(CatalogTag.slug == slug))
    if existing is not None:
        raise CatalogMetadataConflict(f"catalog tag slug already exists: {slug}")
    row = CatalogTag(
        tag_id=tag_id or _new_id(TAG_ID_PREFIX),
        slug=slug,
        display_name=display_name,
    )
    state.add(row)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="tag",
        target_id=row.tag_id,
        action="create",
        actor=actor,
        after={"slug": row.slug, "display_name": row.display_name},
    )
    return row


async def list_catalog_tags(state: AsyncSession) -> list[CatalogTag]:
    return list((await state.scalars(select(CatalogTag).order_by(CatalogTag.slug))).all())


async def get_catalog_tag(state: AsyncSession, tag_id: str) -> CatalogTag:
    row = await state.get(CatalogTag, tag_id)
    if row is None:
        raise CatalogMetadataNotFound("tag", tag_id)
    return row


async def update_catalog_tag(
    state: AsyncSession,
    tag_id: str,
    *,
    slug: str | None = None,
    display_name: str | None = None,
    actor: str = "system",
) -> CatalogTag:
    row = await state.get(CatalogTag, tag_id)
    if row is None:
        raise CatalogMetadataNotFound("tag", tag_id)
    before = {"slug": row.slug, "display_name": row.display_name}
    changed = False
    if slug is not None:
        slug = slug.strip()
        if not _TAG_SLUG_RE.fullmatch(slug):
            raise CatalogMetadataInvalid("tag slug must be lowercase URL-safe text")
        if slug != row.slug:
            existing = await state.scalar(select(CatalogTag).where(CatalogTag.slug == slug))
            if existing is not None:
                raise CatalogMetadataConflict(f"catalog tag slug already exists: {slug}")
            row.slug = slug
            changed = True
    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise CatalogMetadataInvalid("tag display name is required")
        if display_name != row.display_name:
            row.display_name = display_name
            changed = True
    if changed:
        await state.flush()
        await append_catalog_revision(
            state,
            target_type="tag",
            target_id=row.tag_id,
            action="update",
            actor=actor,
            before=before,
            after={"slug": row.slug, "display_name": row.display_name},
        )
    if changed:
        _affected = list(
            (
                await state.scalars(
                    select(CatalogTagAssignment.target_id).where(
                        CatalogTagAssignment.tag_id == tag_id,
                        CatalogTagAssignment.target_type == "entry",
                    )
                )
            ).all()
        )
        for _entry_id in _affected:
            _entry = await state.get(CatalogEntry, _entry_id)
            if _entry is not None:
                await enqueue_catalog_search_outbox(state, entry_id=_entry_id, revision=_entry.revision, action="upsert")
    return row


async def delete_catalog_tag(
    state: AsyncSession,
    tag_id: str,
    *,
    actor: str = "system",
) -> None:
    row = await state.get(CatalogTag, tag_id)
    if row is None:
        raise CatalogMetadataNotFound("tag", tag_id)
    snapshot = {"slug": row.slug, "display_name": row.display_name}
    _affected = list(
        (
            await state.scalars(
                select(CatalogTagAssignment.target_id).where(
                    CatalogTagAssignment.tag_id == tag_id,
                    CatalogTagAssignment.target_type == "entry",
                )
            )
        ).all()
    )
    await state.delete(row)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="tag",
        target_id=tag_id,
        action="delete",
        actor=actor,
        before=snapshot,
    )
    for _entry_id in _affected:
        _entry = await state.get(CatalogEntry, _entry_id)
        if _entry is not None:
            await enqueue_catalog_search_outbox(state, entry_id=_entry_id, revision=_entry.revision, action="upsert")


async def assign_catalog_tag(
    state: AsyncSession,
    *,
    tag_id: str,
    target_type: str,
    target_id: str,
    actor: str = "system",
) -> CatalogTagAssignment:
    tag = await state.get(CatalogTag, tag_id)
    if tag is None:
        raise CatalogMetadataNotFound("tag", tag_id)
    model = _TARGET_MODELS.get(target_type)
    if model is None:
        raise CatalogMetadataInvalid(f"unsupported tag target type: {target_type}")
    if await state.get(model, target_id) is None:
        raise CatalogMetadataNotFound(target_type, target_id)
    existing = await state.get(
        CatalogTagAssignment,
        {"tag_id": tag_id, "target_type": target_type, "target_id": target_id},
    )
    if existing is not None:
        return existing
    row = CatalogTagAssignment(
        tag_id=tag_id,
        target_type=target_type,
        target_id=target_id,
    )
    state.add(row)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type=target_type,
        target_id=target_id,
        action="update",
        actor=actor,
        summary="catalog tag assigned",
        payload={"tag_id": tag_id},
    )
    if target_type == "entry":
        _entry = await state.get(CatalogEntry, target_id)
        if _entry is not None:
            await enqueue_catalog_search_outbox(state, entry_id=target_id, revision=_entry.revision, action="upsert")
    return row


async def remove_catalog_tag_assignment(
    state: AsyncSession,
    *,
    tag_id: str,
    target_type: str,
    target_id: str,
    actor: str = "system",
) -> bool:
    if target_type not in _TARGET_MODELS:
        raise CatalogMetadataInvalid(f"unsupported tag target type: {target_type}")
    result = await state.execute(
        delete(CatalogTagAssignment).where(
            CatalogTagAssignment.tag_id == tag_id,
            CatalogTagAssignment.target_type == target_type,
            CatalogTagAssignment.target_id == target_id,
        )
    )
    removed = bool(result.rowcount)
    if removed:
        await append_catalog_revision(
            state,
            target_type=target_type,
            target_id=target_id,
            action="update",
            actor=actor,
            summary="catalog tag removed",
            payload={"tag_id": tag_id},
        )
    if removed and target_type == "entry":
        _entry = await state.get(CatalogEntry, target_id)
        if _entry is not None:
            await enqueue_catalog_search_outbox(state, entry_id=target_id, revision=_entry.revision, action="upsert")
    return removed


async def create_catalog_relation(
    state: AsyncSession,
    *,
    from_entry_id: str,
    to_entry_id: str,
    relation_type: str,
    note: str = "",
    actor: str = "system",
    relation_id: str | None = None,
) -> CatalogRelation:
    relation_type = relation_type.strip().lower()
    if not relation_type or len(relation_type) > 40:
        raise CatalogMetadataInvalid("relation type is required and must fit 40 characters")
    if from_entry_id == to_entry_id:
        raise CatalogMetadataInvalid("catalog relation cannot target itself")
    for entry_id in (from_entry_id, to_entry_id):
        if await state.get(CatalogEntry, entry_id) is None:
            raise CatalogMetadataNotFound("entry", entry_id)
    existing = await state.scalar(
        select(CatalogRelation).where(
            CatalogRelation.from_entry_id == from_entry_id,
            CatalogRelation.to_entry_id == to_entry_id,
            CatalogRelation.relation_type == relation_type,
        )
    )
    if existing is not None:
        raise CatalogMetadataConflict("catalog relation already exists")
    row = CatalogRelation(
        relation_id=relation_id or _new_id(RELATION_ID_PREFIX),
        from_entry_id=from_entry_id,
        to_entry_id=to_entry_id,
        relation_type=relation_type,
        note=note,
    )
    state.add(row)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="relation",
        target_id=row.relation_id,
        action="create",
        actor=actor,
        after={
            "from_entry_id": from_entry_id,
            "to_entry_id": to_entry_id,
            "relation_type": relation_type,
            "note": note,
        },
    )
    return row


async def list_catalog_relations(
    state: AsyncSession,
    *,
    from_entry_id: str | None = None,
    published_only: bool = False,
) -> list[CatalogRelation]:
    stmt = select(CatalogRelation).order_by(CatalogRelation.created_at)
    if from_entry_id is not None:
        stmt = stmt.where(CatalogRelation.from_entry_id == from_entry_id)
    rows = list((await state.scalars(stmt)).all())
    if not published_only:
        return rows
    visible: list[CatalogRelation] = []
    for row in rows:
        source = await state.get(CatalogEntry, row.from_entry_id)
        target = await state.get(CatalogEntry, row.to_entry_id)
        if source is not None and target is not None:
            if source.status == "published" and target.status == "published":
                visible.append(row)
    return visible


async def delete_catalog_relation(
    state: AsyncSession,
    relation_id: str,
    *,
    actor: str = "system",
) -> None:
    row = await state.get(CatalogRelation, relation_id)
    if row is None:
        raise CatalogMetadataNotFound("relation", relation_id)
    snapshot = {
        "from_entry_id": row.from_entry_id,
        "to_entry_id": row.to_entry_id,
        "relation_type": row.relation_type,
        "note": row.note,
    }
    await state.delete(row)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="relation",
        target_id=relation_id,
        action="delete",
        actor=actor,
        before=snapshot,
    )



async def list_catalog_revisions(
    state: AsyncSession,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[CatalogRevision], int]:
    """Return (rows, total) for filtered, paginated revision browsing.

    Revisions are immutable audit records; this function never mutates them.
    """
    if target_type is not None and target_type not in _REVISION_TARGET_TYPES:
        raise CatalogMetadataInvalid(f"unsupported revision target type: {target_type}")
    if action is not None and action not in _REVISION_ACTIONS:
        raise CatalogMetadataInvalid(f"unsupported revision action: {action}")
    stmt = select(CatalogRevision).order_by(CatalogRevision.created_at, CatalogRevision.revision_id)
    count_stmt = select(func.count()).select_from(CatalogRevision)
    if target_type is not None:
        stmt = stmt.where(CatalogRevision.target_type == target_type)
        count_stmt = count_stmt.where(CatalogRevision.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(CatalogRevision.target_id == target_id)
        count_stmt = count_stmt.where(CatalogRevision.target_id == target_id)
    if action is not None:
        stmt = stmt.where(CatalogRevision.action == action)
        count_stmt = count_stmt.where(CatalogRevision.action == action)
    if actor is not None:
        stmt = stmt.where(CatalogRevision.actor == actor)
        count_stmt = count_stmt.where(CatalogRevision.actor == actor)
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = list((await state.scalars(stmt)).all())
    total = int(await state.scalar(count_stmt) or 0)
    return rows, total
