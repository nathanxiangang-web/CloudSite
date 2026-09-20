"""R1 supplement: identity conflict explicit reporting tests.

Verifies V2 doc section 56 (Identity strict acceptance): when provider
information is insufficient to reliably decide identity, the resolver must
produce an explicit ``identity_conflict`` signal (ambiguous_new match with
populated ambiguous_resource_ids) rather than silently inheriting an old
stable ID. Also covers the rename/move preservation guarantees from the
same section and audit-tests-4 P3 gap item 11.

These tests exercise the public ``resolve_resource_identities`` entry point
over an in-memory StateBase schema and assert:
  1. ambiguous fingerprint candidates yield an explicit conflict signal;
  2. the new resource_id is not silently inherited from any candidate;
  3. the conflict is recorded in the audit log (OperationLog WARNING);
  4. the resolution result carries the conflict list;
  5. file rename preserves the stable resource_id;
  6. file move preserves the stable resource_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.identity import (
    IdentityObservation,
    identity_fingerprint,
    resolve_resource_identities,
)
from cloudsite.models import OperationLog, ResourceIdentity


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def _observation(path: str, *, size: int = 42) -> IdentityObservation:
    return IdentityObservation(
        path=path,
        name=path.rsplit("/", 1)[-1],
        root_mapping_id=1,
        size=size,
        modified_at=NOW,
        extension="zip",
        mime_type="application/zip",
    )


def _fingerprint(size: int = 42) -> str:
    return identity_fingerprint(
        size=size,
        modified_at=NOW,
        extension="zip",
        mime_type="application/zip",
    )


async def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def _seed_identity(factory, resource_id: str, path: str) -> None:
    async with factory() as session:
        session.add(
            ResourceIdentity(
                resource_id=resource_id,
                current_path=path,
                root_mapping_id=1,
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
                last_name=path.rsplit("/", 1)[-1],
                last_extension="zip",
                last_mime_type="application/zip",
                last_size=42,
                last_modified_at=NOW,
                identity_fingerprint=_fingerprint(),
                created_from="legacy_migration",
                updated_at=NOW,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# 1. provider info insufficient -> explicit identity_conflict, no silent inherit
# ---------------------------------------------------------------------------

async def test_identity_conflict_explicit() -> None:
    """Two existing identities share a fingerprint; a new observation with the
    same fingerprint but a different path cannot be reliably matched.

    Per V2 doc section 56 the resolver must produce an explicit
    identity_conflict signal (match_type=ambiguous_new with populated
    ambiguous_resource_ids), not silently inherit either old ID.
    """
    engine, factory = await _make_factory()
    try:
        await _seed_identity(factory, "r_old_a", "/root/a/A.zip")
        await _seed_identity(factory, "r_old_b", "/root/b/A.zip")

        async with factory() as session:
            resolutions = await resolve_resource_identities(
                session,
                [_observation("/root/c/A.zip")],
                visible_paths={"/root/c/A.zip"},
            )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.match_type == "ambiguous_new"
        assert resolution.ambiguous_resource_ids == ["r_old_a", "r_old_b"]
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 2. no silent inheritance of an old ID
# ---------------------------------------------------------------------------

async def test_identity_conflict_no_silent_inheritance() -> None:
    """Under identity_conflict the newly assigned resource_id must not equal
    any of the ambiguous candidate IDs. The resolver must allocate a fresh
    stable ID instead of silently inheriting an old one.
    """
    engine, factory = await _make_factory()
    try:
        await _seed_identity(factory, "r_first", "/root/a/A.zip")
        await _seed_identity(factory, "r_second", "/root/b/A.zip")

        async with factory() as session:
            resolutions = await resolve_resource_identities(
                session,
                [_observation("/root/c/A.zip")],
                visible_paths={"/root/c/A.zip"},
            )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.resource_id not in {"r_first", "r_second"}
        assert resolution.resource_id.startswith("r_")
        assert set(resolution.ambiguous_resource_ids) == {"r_first", "r_second"}
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 3. conflict is recorded in the audit log
# ---------------------------------------------------------------------------

async def test_identity_conflict_logged() -> None:
    """An identity_conflict must be recorded as a WARNING-level OperationLog
    row so operators can see the unresolved ambiguity instead of it being
    silently swallowed.
    """
    engine, factory = await _make_factory()
    try:
        await _seed_identity(factory, "r_left", "/root/a/A.zip")
        await _seed_identity(factory, "r_right", "/root/b/A.zip")

        async with factory() as session:
            await resolve_resource_identities(
                session,
                [_observation("/root/c/A.zip")],
                visible_paths={"/root/c/A.zip"},
            )
            await session.commit()

            logs = list(
                (
                    await session.scalars(
                        select(OperationLog).where(
                            OperationLog.module == "identity",
                            OperationLog.level == "WARNING",
                        )
                    )
                ).all()
            )

        assert len(logs) >= 1
        assert any(
            "ambiguous" in (log.action or "") or "ambiguous" in (log.message or "")
            for log in logs
        )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 4. reconcile/result carries the conflict list
# ---------------------------------------------------------------------------

async def test_identity_conflict_in_reconcile_result() -> None:
    """The resolution result returned to the reconcile caller must carry the
    conflict list (ambiguous_resource_ids) so downstream audit/repair can act
    on it rather than receiving a silently-resolved single ID.
    """
    engine, factory = await _make_factory()
    try:
        await _seed_identity(factory, "r_src_a", "/root/a/A.zip")
        await _seed_identity(factory, "r_src_b", "/root/b/A.zip")

        async with factory() as session:
            resolutions = await resolve_resource_identities(
                session,
                [_observation("/root/c/A.zip")],
                visible_paths={"/root/c/A.zip"},
            )

        conflicts = [r for r in resolutions if r.ambiguous_resource_ids]
        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.match_type == "ambiguous_new"
        assert set(conflict.ambiguous_resource_ids) == {"r_src_a", "r_src_b"}
        assert conflict.resource_id not in {"r_src_a", "r_src_b"}
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. file rename preserves the stable resource_id
# ---------------------------------------------------------------------------

async def test_rename_preserves_identity() -> None:
    """V2 doc section 56: index -> file rename -> reindex -> same resource_id.

    A file observed at /root/A.zip and then at /root/B.zip (same parent
    directory) must keep the same stable resource_id with match_type=rename.
    """
    engine, factory = await _make_factory()
    try:
        await _seed_identity(factory, "r_stable", "/root/A.zip")

        async with factory() as session:
            resolutions = await resolve_resource_identities(
                session,
                [_observation("/root/B.zip")],
                visible_paths={"/root/B.zip"},
                allowed_candidate_paths={"/root/A.zip"},
            )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.resource_id == "r_stable"
        assert resolution.match_type == "rename"
        assert resolution.previous_path == "/root/A.zip"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 6. file move preserves the stable resource_id
# ---------------------------------------------------------------------------

async def test_move_preserves_identity() -> None:
    """V2 doc section 56: index -> file move -> reindex -> same resource_id.

    A file observed at /root/a/A.zip and then at /root/b/A.zip (different
    parent directory) must keep the same stable resource_id with
    match_type=move.
    """
    engine, factory = await _make_factory()
    try:
        await _seed_identity(factory, "r_stable", "/root/a/A.zip")

        async with factory() as session:
            resolutions = await resolve_resource_identities(
                session,
                [_observation("/root/b/A.zip")],
                visible_paths={"/root/b/A.zip"},
            )

        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.resource_id == "r_stable"
        assert resolution.match_type == "move"
        assert resolution.previous_path == "/root/a/A.zip"
    finally:
        await engine.dispose()
