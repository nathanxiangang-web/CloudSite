import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from ..database import IndexSession, StateSession
from ..config import settings
from ..models import (
    OperationLog,
    Resource,
    ResourceIdentity,
    ResourceIdentityHistory,
    SyncRun,
    SystemSetting,
)
from .fingerprint import identity_fingerprint


STABLE_RESOURCE_ID_VERSION = "1"


def backup_stable_id_databases(data_dir: Path | None = None) -> Path | None:
    """Create one persistent pre-0.3.0 snapshot before schema/identity migration."""
    root = (data_dir or settings.data_dir).resolve()
    state_path = root / "state.db"
    index_path = root / "index.db"
    if not state_path.exists() or not index_path.exists():
        return None
    try:
        index = sqlite3.connect(f"{index_path.as_uri()}?mode=ro", uri=True)
        try:
            has_resources = index.execute("SELECT 1 FROM resources LIMIT 1").fetchone() is not None
        finally:
            index.close()
        state = sqlite3.connect(f"{state_path.as_uri()}?mode=ro", uri=True)
        try:
            complete = state.execute(
                "SELECT value FROM system_settings WHERE key='stable_resource_id_migration_status'"
            ).fetchone()
        finally:
            state.close()
    except sqlite3.DatabaseError:
        return None
    if not has_resources or (complete and complete[0] == "complete"):
        return None

    target = root / ".codex-backups" / "pre-0.3.0-stable-id"
    target.mkdir(parents=True, exist_ok=True)
    state_backup = target / "state.db"
    index_backup = target / "index.db"
    if state_backup.exists() and index_backup.exists():
        return target
    for source, destination in ((state_path, state_backup), (index_path, index_backup)):
        temporary = destination.with_suffix(".db.tmp")
        source_db = sqlite3.connect(source)
        target_db = sqlite3.connect(temporary)
        try:
            source_db.backup(target_db)
        finally:
            target_db.close()
            source_db.close()
        temporary.replace(destination)
    return target


async def _set_status(status: str, *, message: str = "") -> None:
    now = datetime.now(timezone.utc)
    async with StateSession() as session:
        for key, value in (
            ("stable_resource_id_version", STABLE_RESOURCE_ID_VERSION),
            ("stable_resource_id_migration_status", status),
            ("stable_resource_id_migration_message", message[:1000]),
        ):
            row = await session.get(SystemSetting, key)
            if row is None:
                session.add(SystemSetting(key=key, value=value, value_type="string", updated_at=now))
            else:
                row.value = value
                row.value_type = "string"
                row.updated_at = now
        await session.commit()


async def migrate_stable_resource_ids() -> int:
    """Seed existing IDs without rewriting a single index Resource ID."""
    async with StateSession() as state:
        status = await state.get(SystemSetting, "stable_resource_id_migration_status")
        if status and status.value == "complete":
            identity_ids = set((await state.scalars(select(ResourceIdentity.resource_id))).all())
            total = len(identity_ids)
            async with IndexSession() as index:
                active_ids = set(
                    (
                        await index.scalars(
                            select(Resource.id).where(Resource.status == "active")
                        )
                    ).all()
                )
            missing = active_ids - identity_ids
            if missing:
                raise RuntimeError(
                    f"Stable ID 注册表不完整：{len(missing)} 个活跃资源缺少身份记录"
                )
            return total

    async with IndexSession() as index:
        running = int(
            await index.scalar(
                select(func.count()).select_from(SyncRun).where(SyncRun.status == "running")
            )
            or 0
        )
        if running:
            raise RuntimeError("Stable ID 迁移前存在运行中的同步任务")
        resources = list(
            (await index.scalars(select(Resource).where(Resource.status == "active"))).all()
        )

    await _set_status("running")
    now = datetime.now(timezone.utc)
    try:
        async with StateSession() as state:
            for resource in resources:
                identity = await state.get(ResourceIdentity, resource.id)
                if identity is not None:
                    continue
                fingerprint = identity_fingerprint(
                    size=resource.size,
                    modified_at=resource.modified_at,
                    extension=resource.extension,
                    mime_type=resource.mime_type,
                )
                state.add(
                    ResourceIdentity(
                        resource_id=resource.id,
                        current_path=resource.path,
                        root_mapping_id=resource.root_mapping_id,
                        status="active",
                        first_seen_at=resource.indexed_at or now,
                        last_seen_at=now,
                        last_name=resource.name,
                        last_extension=resource.extension,
                        last_mime_type=resource.mime_type,
                        last_size=resource.size,
                        last_modified_at=resource.modified_at,
                        identity_fingerprint=fingerprint,
                        fingerprint_version=1,
                        created_from="legacy_migration",
                        updated_at=now,
                    )
                )
                state.add(
                    ResourceIdentityHistory(
                        resource_id=resource.id,
                        path=resource.path,
                        event_type="created",
                        first_observed_at=resource.indexed_at or now,
                        last_observed_at=now,
                        to_path=resource.path,
                        created_at=now,
                    )
                )
            await state.commit()

            ids = set(
                (await state.scalars(select(ResourceIdentity.resource_id))).all()
            )
            missing = [resource.id for resource in resources if resource.id not in ids]
            if missing:
                raise RuntimeError(f"Stable ID 迁移验证失败：缺少 {len(missing)} 个资源身份")
            total = int(await state.scalar(select(func.count()).select_from(ResourceIdentity)) or 0)
            state.add(
                OperationLog(
                    level="INFO",
                    module="identity",
                    action="identity_registry_seeded",
                    message=f"Stable ID 注册表已幂等迁移：保留 {len(resources)} 个既有 Resource ID",
                )
            )
            await state.commit()
        await _set_status("complete")
        return total
    except Exception as exc:
        await _set_status("failed", message=str(exc))
        raise
