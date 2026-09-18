"""Persistence-free resource identity matching decisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ..domain.rules import normalize_identity_path


@dataclass(frozen=True, slots=True)
class ResourceIdentityCandidateView:
    resource_id: str
    current_path: str | None


@dataclass(frozen=True, slots=True)
class ResourceIdentityMatchDecision:
    match_type: str
    resource_id: str | None = None
    previous_path: str | None = None
    ambiguous_resource_ids: tuple[str, ...] = ()


def choose_fingerprint_match(
    *,
    observation_path: str,
    fingerprint_candidates: list[ResourceIdentityCandidateView],
    normalized_visible_paths: set[str],
    claimed_resource_ids: set[str],
    allowed_candidate_paths: set[str] | None = None,
    defer_unseen_candidates: bool = False,
) -> ResourceIdentityMatchDecision:
    """Choose a conservative fingerprint match for a path with no exact match.

    This function intentionally does not allocate IDs or mutate persistence.
    It mirrors the legacy resolver's candidate policy:
    - candidates whose current path is still visible are copies, not moves;
    - an optional rolling-scope allowlist restricts move candidates;
    - one allowed candidate is rename/move;
    - one unseen-but-out-of-scope candidate may be deferred;
    - multiple candidates are ambiguous and require a new stable ID.
    """
    normalized_path = normalize_identity_path(observation_path)
    unseen_candidates = [
        candidate
        for candidate in fingerprint_candidates
        if candidate.resource_id not in claimed_resource_ids
        and candidate.current_path
        and normalize_identity_path(candidate.current_path) not in normalized_visible_paths
    ]
    candidates = [
        candidate
        for candidate in unseen_candidates
        if allowed_candidate_paths is None
        or normalize_identity_path(candidate.current_path or "/") in allowed_candidate_paths
    ]

    if len(candidates) == 1:
        matched = candidates[0]
        previous_path = matched.current_path or "/"
        match_type = (
            "rename"
            if PurePosixPath(previous_path).parent == PurePosixPath(normalized_path).parent
            else "move"
        )
        return ResourceIdentityMatchDecision(
            match_type=match_type,
            resource_id=matched.resource_id,
            previous_path=matched.current_path,
        )

    if not candidates and defer_unseen_candidates and len(unseen_candidates) == 1:
        pending = unseen_candidates[0]
        return ResourceIdentityMatchDecision(
            match_type="pending_move_or_copy",
            resource_id=pending.resource_id,
            previous_path=pending.current_path,
        )

    ambiguous_candidates = candidates or unseen_candidates
    if len(ambiguous_candidates) > 1:
        return ResourceIdentityMatchDecision(
            match_type="ambiguous_new",
            ambiguous_resource_ids=tuple(
                sorted(candidate.resource_id for candidate in ambiguous_candidates)
            ),
        )

    return ResourceIdentityMatchDecision(match_type="new")


__all__ = [
    "ResourceIdentityCandidateView",
    "ResourceIdentityMatchDecision",
    "choose_fingerprint_match",
]
