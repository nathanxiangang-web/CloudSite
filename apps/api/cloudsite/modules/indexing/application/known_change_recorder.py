from __future__ import annotations

from ..domain.provider_change import ProviderChange, ProviderChangeSource, ProviderChangeType


class KnownChangeRecorder:
    """Record CloudSite-initiated operations as ProviderChange events (V2 §26).

    When CloudSite successfully completes an upload, delete, rename, move,
    or directory creation, the change is recorded directly as a
    ProviderChange with source=CLOUDSITE, avoiding a full root re-scan.
    """

    def record_create(
        self, root_mapping_id: int, path: str, is_dir: bool = False,
        provider_object_id: str | None = None, resource_id: str | None = None,
    ) -> ProviderChange:
        return ProviderChange(
            change_type=ProviderChangeType.CREATE,
            root_mapping_id=root_mapping_id,
            path=path,
            is_dir=is_dir,
            provider_object_id=provider_object_id,
            resource_id=resource_id,
            source=ProviderChangeSource.CLOUDSITE,
        )

    def record_update(
        self, root_mapping_id: int, path: str, is_dir: bool = False,
        provider_object_id: str | None = None, resource_id: str | None = None,
    ) -> ProviderChange:
        return ProviderChange(
            change_type=ProviderChangeType.UPDATE,
            root_mapping_id=root_mapping_id,
            path=path,
            is_dir=is_dir,
            provider_object_id=provider_object_id,
            resource_id=resource_id,
            source=ProviderChangeSource.CLOUDSITE,
        )

    def record_delete(
        self, root_mapping_id: int, path: str, is_dir: bool = False,
        provider_object_id: str | None = None, resource_id: str | None = None,
    ) -> ProviderChange:
        return ProviderChange(
            change_type=ProviderChangeType.DELETE,
            root_mapping_id=root_mapping_id,
            path=path,
            is_dir=is_dir,
            provider_object_id=provider_object_id,
            resource_id=resource_id,
            source=ProviderChangeSource.CLOUDSITE,
        )

    def record_rename(
        self, root_mapping_id: int, old_path: str, new_path: str,
        is_dir: bool = False, provider_object_id: str | None = None,
        resource_id: str | None = None,
    ) -> ProviderChange:
        return ProviderChange(
            change_type=ProviderChangeType.RENAME,
            root_mapping_id=root_mapping_id,
            path=new_path,
            old_path=old_path,
            is_dir=is_dir,
            provider_object_id=provider_object_id,
            resource_id=resource_id,
            source=ProviderChangeSource.CLOUDSITE,
        )

    def record_move(
        self, root_mapping_id: int, old_path: str, new_path: str,
        is_dir: bool = False, provider_object_id: str | None = None,
        resource_id: str | None = None,
    ) -> ProviderChange:
        return ProviderChange(
            change_type=ProviderChangeType.MOVE,
            root_mapping_id=root_mapping_id,
            path=new_path,
            old_path=old_path,
            is_dir=is_dir,
            provider_object_id=provider_object_id,
            resource_id=resource_id,
            source=ProviderChangeSource.CLOUDSITE,
        )

    def record_directory_dirty(
        self, root_mapping_id: int, path: str,
    ) -> ProviderChange:
        return ProviderChange(
            change_type=ProviderChangeType.DIRECTORY_DIRTY,
            root_mapping_id=root_mapping_id,
            path=path,
            is_dir=True,
            source=ProviderChangeSource.CLOUDSITE,
        )


__all__ = ["KnownChangeRecorder"]
