"""SQLAlchemy adapter for the Identity resource repository port."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.records import ResourceIdentityHistoryRecord, ResourceIdentityRecord
from ..application.ports import ResourceIdentityRepository
from .models import ResourceIdentity, ResourceIdentityHistory


class SqlAlchemyResourceIdentityRepository(ResourceIdentityRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._entities: dict[str, ResourceIdentity] = {}

    @staticmethod
    def _to_record(entity: ResourceIdentity) -> ResourceIdentityRecord:
        return ResourceIdentityRecord(
            resource_id=entity.resource_id,
            current_path=entity.current_path,
            root_mapping_id=entity.root_mapping_id,
            status=entity.status,
            first_seen_at=entity.first_seen_at,
            last_seen_at=entity.last_seen_at,
            last_name=entity.last_name,
            last_extension=entity.last_extension,
            last_mime_type=entity.last_mime_type,
            last_size=entity.last_size,
            last_modified_at=entity.last_modified_at,
            provider_object_id=entity.provider_object_id,
            content_hash=entity.content_hash,
            identity_fingerprint=entity.identity_fingerprint,
            fingerprint_version=entity.fingerprint_version,
            created_from=entity.created_from,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _apply(entity: ResourceIdentity, record: ResourceIdentityRecord) -> None:
        entity.current_path = record.current_path
        entity.root_mapping_id = record.root_mapping_id
        entity.status = record.status
        entity.first_seen_at = record.first_seen_at
        entity.last_seen_at = record.last_seen_at
        entity.last_name = record.last_name
        entity.last_extension = record.last_extension
        entity.last_mime_type = record.last_mime_type
        entity.last_size = record.last_size
        entity.last_modified_at = record.last_modified_at
        entity.provider_object_id = record.provider_object_id
        entity.content_hash = record.content_hash
        entity.identity_fingerprint = record.identity_fingerprint
        entity.fingerprint_version = record.fingerprint_version
        entity.created_from = record.created_from
        entity.updated_at = record.updated_at

    async def list_for_roots(
        self, root_mapping_ids: set[int | None]
    ) -> list[ResourceIdentityRecord]:
        statement = select(ResourceIdentity)
        if root_mapping_ids and None not in root_mapping_ids:
            statement = statement.where(
                ResourceIdentity.root_mapping_id.in_(root_mapping_ids)
            )
        entities = list((await self._session.scalars(statement)).all())
        for entity in entities:
            self._entities[entity.resource_id] = entity
        return [self._to_record(entity) for entity in entities]

    async def id_exists(self, resource_id: str) -> bool:
        if resource_id in self._entities:
            return True
        entity = await self._session.get(ResourceIdentity, resource_id)
        if entity is not None:
            self._entities[resource_id] = entity
            return True
        return False

    async def add(self, record: ResourceIdentityRecord) -> None:
        entity = ResourceIdentity(
            resource_id=record.resource_id,
            current_path=record.current_path,
            root_mapping_id=record.root_mapping_id,
            status=record.status,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            last_name=record.last_name,
            last_extension=record.last_extension,
            last_mime_type=record.last_mime_type,
            last_size=record.last_size,
            last_modified_at=record.last_modified_at,
            provider_object_id=record.provider_object_id,
            content_hash=record.content_hash,
            identity_fingerprint=record.identity_fingerprint,
            fingerprint_version=record.fingerprint_version,
            created_from=record.created_from,
            updated_at=record.updated_at,
        )
        self._session.add(entity)
        self._entities[record.resource_id] = entity

    async def save(self, record: ResourceIdentityRecord) -> None:
        entity = self._entities.get(record.resource_id)
        if entity is None:
            entity = await self._session.get(ResourceIdentity, record.resource_id)
            if entity is None:
                raise RuntimeError(
                    f"Identity repository cannot save unknown resource: {record.resource_id}"
                )
            self._entities[record.resource_id] = entity
        self._apply(entity, record)

    async def add_history(self, record: ResourceIdentityHistoryRecord) -> None:
        self._session.add(
            ResourceIdentityHistory(
                resource_id=record.resource_id,
                path=record.path,
                event_type=record.event_type,
                first_observed_at=record.first_observed_at,
                last_observed_at=record.last_observed_at,
                from_path=record.from_path,
                to_path=record.to_path,
                cycle_id=record.cycle_id,
                created_at=record.created_at,
            )
        )

    async def commit(self) -> None:
        await self._session.commit()


__all__ = ["SqlAlchemyResourceIdentityRepository"]
