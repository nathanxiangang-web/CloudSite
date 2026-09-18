"""Pure resource identity matching decision tests."""

from cloudsite.modules.identity.application.matching import (
    ResourceIdentityCandidateView,
    choose_fingerprint_match,
)
from cloudsite.modules.identity.domain.rules import (
    classify_identity_event,
    normalize_identity_path,
)


def candidate(resource_id: str, path: str) -> ResourceIdentityCandidateView:
    return ResourceIdentityCandidateView(resource_id=resource_id, current_path=path)


def test_normalize_identity_path_matches_legacy_behavior():
    assert normalize_identity_path("\\a//b/") == "/a/b"
    assert normalize_identity_path("") == "/"


def test_classify_identity_event_preserves_created_observed_reactivated_rename_move():
    assert classify_identity_event(None, "/a", "active") == "created"
    assert classify_identity_event("/a", "/a", "active") == "observed"
    assert classify_identity_event("/a", "/a", "missing") == "reactivated"
    assert classify_identity_event("/root/a", "/root/b", "active") == "rename"
    assert classify_identity_event("/root/a", "/other/a", "active") == "move"


def test_visible_same_fingerprint_is_copy_not_move():
    result = choose_fingerprint_match(
        observation_path="/copy/A.zip",
        fingerprint_candidates=[candidate("r_original", "/source/A.zip")],
        normalized_visible_paths={"/source/A.zip", "/copy/A.zip"},
        claimed_resource_ids=set(),
    )
    assert result.match_type == "new"
    assert result.resource_id is None


def test_unique_unseen_candidate_classifies_rename_or_move():
    renamed = choose_fingerprint_match(
        observation_path="/root/B.zip",
        fingerprint_candidates=[candidate("r_one", "/root/A.zip")],
        normalized_visible_paths={"/root/B.zip"},
        claimed_resource_ids=set(),
    )
    assert renamed.match_type == "rename"
    assert renamed.resource_id == "r_one"
    assert renamed.previous_path == "/root/A.zip"

    moved = choose_fingerprint_match(
        observation_path="/other/A.zip",
        fingerprint_candidates=[candidate("r_one", "/root/A.zip")],
        normalized_visible_paths={"/other/A.zip"},
        claimed_resource_ids=set(),
    )
    assert moved.match_type == "move"


def test_claimed_candidate_is_not_reused():
    result = choose_fingerprint_match(
        observation_path="/other/A.zip",
        fingerprint_candidates=[candidate("r_one", "/root/A.zip")],
        normalized_visible_paths={"/other/A.zip"},
        claimed_resource_ids={"r_one"},
    )
    assert result.match_type == "new"


def test_rolling_scope_can_defer_single_unseen_candidate():
    result = choose_fingerprint_match(
        observation_path="/new/A.zip",
        fingerprint_candidates=[candidate("r_one", "/outside/A.zip")],
        normalized_visible_paths={"/new/A.zip"},
        claimed_resource_ids=set(),
        allowed_candidate_paths={"/inside/A.zip"},
        defer_unseen_candidates=True,
    )
    assert result.match_type == "pending_move_or_copy"
    assert result.resource_id == "r_one"
    assert result.previous_path == "/outside/A.zip"


def test_multiple_candidates_are_ambiguous_and_sorted():
    result = choose_fingerprint_match(
        observation_path="/new/A.zip",
        fingerprint_candidates=[
            candidate("r_z", "/old/z.zip"),
            candidate("r_a", "/old/a.zip"),
        ],
        normalized_visible_paths={"/new/A.zip"},
        claimed_resource_ids=set(),
    )
    assert result.match_type == "ambiguous_new"
    assert result.ambiguous_resource_ids == ("r_a", "r_z")
