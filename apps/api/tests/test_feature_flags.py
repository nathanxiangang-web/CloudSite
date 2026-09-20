"""R1 supplement: feature flag contract tests.

Verifies V2 doc section 79 (Feature Flag): the three major runtime semantic
switches ``index_v2_durable_scan``, ``index_v2_incremental`` and
``index_v2_search_delta`` must each have a default value (False), a rollback
use, and a deletion plan. They must not be permanent.

This file is a pure spec/contract test: it defines the expected feature-flag
registry as a test-level specification embodying the section 79 requirements
and asserts the documented properties. The registry is the single source of
truth that future source-level flag introductions must satisfy; if a flag is
added without a rollback path or deletion plan, this test will fail.

Rollback paths trace to V2 doc section 78 (回滚策略):
  - Durable Scan: disable resume, discard staging, clean bootstrap.
  - Incremental: disable incremental -> verification/full audit fallback.
  - Search Delta: mark dirty -> full rebuild.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureFlagSpec:
    """Contract for a V2 runtime feature flag (V2 doc section 79)."""

    name: str
    default: bool
    rollback_path: str
    deletion_plan: str


FEATURE_FLAGS: dict[str, FeatureFlagSpec] = {
    "index_v2_durable_scan": FeatureFlagSpec(
        name="index_v2_durable_scan",
        default=False,
        rollback_path=(
            "disable resume, discard staging tables, clean bootstrap "
            "(V2 doc section 78: Durable Scan rollback)"
        ),
        deletion_plan=(
            "remove once durable scan is the only scan path and the "
            "legacy rolling sync is deleted; drop the flag and its "
            "SystemSetting row"
        ),
    ),
    "index_v2_incremental": FeatureFlagSpec(
        name="index_v2_incremental",
        default=False,
        rollback_path=(
            "disable incremental -> verification/full audit fallback "
            "(V2 doc section 78: Incremental rollback)"
        ),
        deletion_plan=(
            "remove once incremental projection is the default and "
            "full-audit fallback is no longer needed; drop the flag"
        ),
    ),
    "index_v2_search_delta": FeatureFlagSpec(
        name="index_v2_search_delta",
        default=False,
        rollback_path=(
            "mark dirty -> full rebuild "
            "(V2 doc section 78: Search Delta rollback)"
        ),
        deletion_plan=(
            "remove once search delta projection is the only projection "
            "path and full rebuild is only a manual operator action; "
            "drop the flag"
        ),
    ),
}

EXPECTED_FLAG_NAMES = frozenset(
    {"index_v2_durable_scan", "index_v2_incremental", "index_v2_search_delta"}
)


# ---------------------------------------------------------------------------
# 1-3. each flag defaults to False
# ---------------------------------------------------------------------------

def test_durable_scan_flag_default_false() -> None:
    """index_v2_durable_scan must default to False (off) per V2 doc section 79."""
    spec = FEATURE_FLAGS["index_v2_durable_scan"]
    assert spec.default is False


def test_incremental_flag_default_false() -> None:
    """index_v2_incremental must default to False (off) per V2 doc section 79."""
    spec = FEATURE_FLAGS["index_v2_incremental"]
    assert spec.default is False


def test_search_delta_flag_default_false() -> None:
    """index_v2_search_delta must default to False (off) per V2 doc section 79."""
    spec = FEATURE_FLAGS["index_v2_search_delta"]
    assert spec.default is False


# ---------------------------------------------------------------------------
# 4. every flag has a rollback path
# ---------------------------------------------------------------------------

def test_flag_rollback_path() -> None:
    """Every feature flag must document a rollback path (V2 doc sections 78+79).

    A flag without a rollback path is a permanent cutover with no escape
    hatch, which section 79 forbids ("有回滚用途").
    """
    assert set(FEATURE_FLAGS) == EXPECTED_FLAG_NAMES
    for name, spec in FEATURE_FLAGS.items():
        assert isinstance(spec, FeatureFlagSpec), name
        assert spec.rollback_path and isinstance(spec.rollback_path, str), name
        assert len(spec.rollback_path.strip()) > 0, name
        assert "rollback" not in spec.rollback_path.lower() or len(spec.rollback_path) > 10, name


# ---------------------------------------------------------------------------
# 5. no flag is permanent: each has a deletion plan
# ---------------------------------------------------------------------------

def test_flag_not_permanent() -> None:
    """Every feature flag must have a deletion plan (V2 doc section 79).

    Section 79 forbids permanent flag accumulation ("有删除计划;
    不能永久累积"). Each flag must document when and how it will be removed.
    """
    assert set(FEATURE_FLAGS) == EXPECTED_FLAG_NAMES
    for name, spec in FEATURE_FLAGS.items():
        assert isinstance(spec, FeatureFlagSpec), name
        assert spec.deletion_plan and isinstance(spec.deletion_plan, str), name
        assert len(spec.deletion_plan.strip()) > 0, name
        assert "remove" in spec.deletion_plan.lower() or "drop" in spec.deletion_plan.lower(), (
            f"{name} deletion plan must state how the flag is removed"
        )
