"""One-shot production rolling verification for Generic Provider roots.

This service intentionally does not own scheduling. It verifies a bounded batch
against durable per-directory baselines and records mismatches into the existing
index_dirty_scopes queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

from cloudsite.modules.providers.contracts.public import ProviderScanPort, ProviderScanRoot

from ..application.verification_batch_selector import (
    VerificationBatchSelector,
    VerificationCandidate,
)
from ..domain.directory_fingerprint import generate_fingerprint
from .alist_adapter import _join_path, _normalize_path, _should_ignore
from .dirty_scope_repository import DirtyScopeRepository
from .verification_state_repository import VerificationStateRepository


@dataclass(slots=True)
class RollingVerificationSummary:
    root_mapping_id: int
    status: str = "success"
    selected: int = 0
    checked: int = 0
    unchanged: int = 0
    dirty: int = 0
    failed: int = 0
    dirty_paths: list[str] = field(default_factory=list)
    failed_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _relative_depth(root_path: str, path: str) -> int:
    root = _normalize_path(root_path)
    current = _normalize_path(path)
    if current == root:
        return 0
    prefix = root.rstrip("/") + "/"
    if not current.startswith(prefix):
        return max(len(PurePosixPath(current).parts) - 1, 0)
    relative = current[len(prefix):]
    return len(PurePosixPath(relative).parts)


def _fingerprint_entries(path: str, items: list[dict]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        item_path = _join_path(path, name)
        if _should_ignore(item_path):
            continue
        is_dir = bool(item.get("is_dir"))
        entries.append(
            {
                "name": name,
                "is_dir": is_dir,
                "size": None if is_dir else int(item.get("size") or 0),
                "modified": item.get("modified") or item.get("updated_at") or "",
                # Generic AList durable baselines intentionally do not depend
                # on provider-native object ids. Keep the same contract here.
                "provider_object_id": "",
            }
        )
    return entries


def _dirty_priority(candidate: VerificationCandidate) -> int:
    # VerificationPriority is lower-is-higher; dirty scopes are higher-is-higher.
    return max(1, 100 - int(candidate.verification_priority))


class RollingVerificationService:
    """Verify one bounded batch for one provider root.

    The caller owns the State DB transaction and should commit the resulting
    verification-state / dirty-scope writes.
    """

    def __init__(self, *, batch_size: int = 20) -> None:
        self._selector = VerificationBatchSelector(batch_size=batch_size)

    async def verify_root(
        self,
        *,
        provider: ProviderScanPort,
        root: ProviderScanRoot,
        verification_state: VerificationStateRepository,
        dirty_scopes: DirtyScopeRepository,
        now: datetime | None = None,
    ) -> RollingVerificationSummary:
        now = now or datetime.now(timezone.utc)
        summary = RollingVerificationSummary(root_mapping_id=root.root_mapping_id)

        records = await verification_state.list_for_root(root.root_mapping_id)
        if not records:
            summary.status = "baseline_required"
            return summary

        candidates = [
            VerificationCandidate(
                root_mapping_id=root.root_mapping_id,
                path=record.path,
                depth=_relative_depth(root.storage_path, record.path),
                last_verified_at=_parse_time(record.last_verified_at),
                last_changed_at=_parse_time(record.last_changed_at),
                previously_failed=bool(record.last_error_code),
            )
            for record in records
        ]
        selected = self._selector.select(candidates, now=now)
        summary.selected = len(selected)

        records_by_path = {record.path: record for record in records}

        for candidate in selected:
            previous = records_by_path[candidate.path]
            try:
                items = await provider.list_path(candidate.path)
                current = generate_fingerprint(
                    candidate.path,
                    _fingerprint_entries(candidate.path, items),
                )
            except Exception as exc:  # noqa: BLE001 - isolate one directory
                await verification_state.mark_failed(
                    root.root_mapping_id,
                    candidate.path,
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:1000],
                )
                summary.failed += 1
                summary.failed_paths.append(candidate.path)
                summary.errors.append(
                    f"{candidate.path}: {type(exc).__name__}: {exc}"
                )
                continue

            summary.checked += 1
            changed = (
                previous.fingerprint is None
                or previous.fingerprint != current.hash
                or previous.child_count != current.child_count
            )
            verified_at = now.isoformat()
            await verification_state.mark_verified(
                root.root_mapping_id,
                candidate.path,
                fingerprint=current.hash,
                child_count=current.child_count,
                changed=changed,
                verified_at=verified_at,
            )

            if not changed:
                summary.unchanged += 1
                continue

            priority = _dirty_priority(candidate)
            existing = await dirty_scopes.get_by_path(
                root.root_mapping_id,
                candidate.path,
            )
            if existing is None:
                await dirty_scopes.add(
                    root.root_mapping_id,
                    candidate.path,
                    reason="verification_mismatch",
                    priority=priority,
                )
            elif existing.status in {"resolved", "failed", "escalated"}:
                await dirty_scopes.reopen(
                    existing.id,
                    reason="verification_mismatch",
                    priority=priority,
                )

            summary.dirty += 1
            summary.dirty_paths.append(candidate.path)

        if summary.failed:
            summary.status = "partial"
        return summary


__all__ = ["RollingVerificationSummary", "RollingVerificationService"]
