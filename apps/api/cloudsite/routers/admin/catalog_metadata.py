"""Administrator Catalog metadata routes: tags, assignments, relations, revisions.

Registered under the existing admin middleware boundary. Anonymous requests are
rejected by the middleware before reaching any handler here. Domain errors from
the metadata service are translated to stable 404/409/400 envelopes.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from ...catalog_metadata_schemas import (
    CatalogRelationCreateInput,
    CatalogRelationSummary,
    CatalogRevisionListOutput,
    CatalogRevisionSummary,
    CatalogTagAssignmentInput,
    CatalogTagAssignmentSummary,
    CatalogTagCreateInput,
    CatalogTagSummary,
    CatalogTagUpdateInput,
)

router = APIRouter()


def _metadata_service():
    from ...services import catalog_metadata  # noqa: PLC0415

    return catalog_metadata


def _translate_metadata_error(exc: Exception) -> HTTPException:
    service = _metadata_service()
    if isinstance(exc, service.CatalogMetadataNotFound):
        return HTTPException(
            404,
            {"code": "CATALOG_METADATA_NOT_FOUND", "message": str(exc)},
        )
    if isinstance(exc, service.CatalogMetadataConflict):
        return HTTPException(
            409,
            {"code": "CATALOG_METADATA_CONFLICT", "message": str(exc)},
        )
    if isinstance(exc, service.CatalogMetadataInvalid):
        return HTTPException(
            400,
            {"code": "CATALOG_METADATA_INVALID", "message": str(exc)},
        )
    return HTTPException(500, {"code": "CATALOG_METADATA_ERROR", "message": "Catalog metadata error"})


def _tag_to_summary(tag) -> CatalogTagSummary:
    return CatalogTagSummary(
        tag_id=tag.tag_id,
        slug=tag.slug,
        display_name=tag.display_name,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


def _assignment_to_summary(assignment) -> CatalogTagAssignmentSummary:
    return CatalogTagAssignmentSummary(
        tag_id=assignment.tag_id,
        target_type=assignment.target_type,
        target_id=assignment.target_id,
        created_at=assignment.created_at,
    )


def _relation_to_summary(relation) -> CatalogRelationSummary:
    return CatalogRelationSummary(
        relation_id=relation.relation_id,
        from_entry_id=relation.from_entry_id,
        to_entry_id=relation.to_entry_id,
        relation_type=relation.relation_type,
        note=relation.note,
        created_at=relation.created_at,
    )


def _decode_json(raw: str) -> dict | None:
    if not raw or raw == "{}":
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _revision_to_summary(revision) -> CatalogRevisionSummary:
    return CatalogRevisionSummary(
        revision_id=revision.revision_id,
        target_type=revision.target_type,
        target_id=revision.target_id,
        action=revision.action,
        actor=revision.actor,
        source=revision.source,
        base_revision=revision.base_revision,
        resulting_revision=revision.resulting_revision,
        summary=revision.summary,
        before=_decode_json(revision.before_json),
        after=_decode_json(revision.after_json),
        diff=_decode_json(revision.diff_json),
        payload=_decode_json(revision.payload_json),
        created_at=revision.created_at,
    )


def _total_pages(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


# ---- Tags ----

@router.get("/api/admin/catalog/metadata/tags", response_model=list[CatalogTagSummary])
async def admin_catalog_tags_list():
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        tags = await service.list_catalog_tags(state)
        return [_tag_to_summary(tag) for tag in tags]


@router.post("/api/admin/catalog/metadata/tags", response_model=CatalogTagSummary, status_code=201)
async def admin_catalog_tags_create(payload: CatalogTagCreateInput):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        try:
            tag = await service.create_catalog_tag(
                state,
                slug=payload.slug,
                display_name=payload.display_name,
                actor="admin",
            )
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()
        return _tag_to_summary(tag)


@router.patch("/api/admin/catalog/metadata/tags/{tag_id}", response_model=CatalogTagSummary)
async def admin_catalog_tags_update(tag_id: str, payload: CatalogTagUpdateInput):
    from ...main import StateSession

    service = _metadata_service()
    values = payload.model_dump(exclude_unset=True)
    async with StateSession() as state:
        try:
            tag = await service.update_catalog_tag(
                state,
                tag_id,
                actor="admin",
                **values,
            )
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()
        return _tag_to_summary(tag)


# ---- Tag assignments ----

@router.post(
    "/api/admin/catalog/metadata/tags/assignments",
    response_model=CatalogTagAssignmentSummary,
    status_code=201,
)
async def admin_catalog_tag_assign(payload: CatalogTagAssignmentInput):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        try:
            assignment = await service.assign_catalog_tag(
                state,
                tag_id=payload.tag_id,
                target_type=payload.target_type,
                target_id=payload.target_id,
                actor="admin",
            )
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()
        return _assignment_to_summary(assignment)


@router.delete("/api/admin/catalog/metadata/tags/assignments", status_code=204)
async def admin_catalog_tag_unassign(payload: CatalogTagAssignmentInput):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        try:
            await service.remove_catalog_tag_assignment(
                state,
                tag_id=payload.tag_id,
                target_type=payload.target_type,
                target_id=payload.target_id,
                actor="admin",
            )
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()


@router.delete("/api/admin/catalog/metadata/tags/{tag_id}", status_code=204)
async def admin_catalog_tags_delete(tag_id: str):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        try:
            await service.delete_catalog_tag(state, tag_id, actor="admin")
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()


# ---- Relations ----

@router.get("/api/admin/catalog/metadata/relations", response_model=list[CatalogRelationSummary])
async def admin_catalog_relations_list(from_entry_id: str | None = Query(default=None)):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        relations = await service.list_catalog_relations(state, from_entry_id=from_entry_id)
        return [_relation_to_summary(relation) for relation in relations]


@router.post(
    "/api/admin/catalog/metadata/relations",
    response_model=CatalogRelationSummary,
    status_code=201,
)
async def admin_catalog_relations_create(payload: CatalogRelationCreateInput):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        try:
            relation = await service.create_catalog_relation(
                state,
                from_entry_id=payload.from_entry_id,
                to_entry_id=payload.to_entry_id,
                relation_type=payload.relation_type,
                note=payload.note,
                actor="admin",
            )
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()
        return _relation_to_summary(relation)


@router.delete("/api/admin/catalog/metadata/relations/{relation_id}", status_code=204)
async def admin_catalog_relations_delete(relation_id: str):
    from ...main import StateSession

    service = _metadata_service()
    async with StateSession() as state:
        try:
            await service.delete_catalog_relation(state, relation_id, actor="admin")
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        await state.commit()


# ---- Revisions (immutable, paginated, filterable) ----

@router.get("/api/admin/catalog/metadata/revisions", response_model=CatalogRevisionListOutput)
async def admin_catalog_revisions_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None),
):
    from ...main import StateSession

    service = _metadata_service()
    offset = (page - 1) * page_size
    async with StateSession() as state:
        try:
            rows, total = await service.list_catalog_revisions(
                state,
                target_type=target_type,
                target_id=target_id,
                action=action,
                actor=actor,
                limit=page_size,
                offset=offset,
            )
        except service.CatalogMetadataError as exc:
            raise _translate_metadata_error(exc) from exc
        return CatalogRevisionListOutput(
            items=[_revision_to_summary(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=_total_pages(total, page_size),
        )
