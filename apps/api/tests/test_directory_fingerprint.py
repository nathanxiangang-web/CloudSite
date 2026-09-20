"""R6 PR03: Directory Fingerprint tests (V2 doc section 31).

Verifies that generate_fingerprint produces a stable, order-independent
SHA-256 hash over directory child entries, and that compare_fingerprints
correctly reports matching and mismatched fingerprints.
"""
from __future__ import annotations

from cloudsite.modules.indexing.domain.directory_fingerprint import (
    DirectoryFingerprint,
    compare_fingerprints,
    generate_fingerprint,
)


def _entry(name: str, **overrides) -> dict:
    base = {
        "name": name,
        "is_dir": False,
        "size": 100,
        "modified": "2026-09-20T00:00:00Z",
    }
    base.update(overrides)
    return base


# =====================================================================
# generate_fingerprint
# =====================================================================

def test_fingerprint_generated() -> None:
    entries = [
        _entry("a.txt", size=10),
        _entry("b.txt", size=20),
    ]
    fp = generate_fingerprint("/dir", entries)
    assert isinstance(fp, DirectoryFingerprint)
    assert fp.path == "/dir"
    assert isinstance(fp.hash, str) and len(fp.hash) == 64
    assert fp.child_count == 2
    assert fp.generated_at


def test_fingerprint_stable_order() -> None:
    entries_a = [_entry("a.txt"), _entry("b.txt"), _entry("c.txt")]
    entries_b = [_entry("c.txt"), _entry("a.txt"), _entry("b.txt")]
    entries_c = [_entry("b.txt"), _entry("c.txt"), _entry("a.txt")]
    fp_a = generate_fingerprint("/dir", entries_a)
    fp_b = generate_fingerprint("/dir", entries_b)
    fp_c = generate_fingerprint("/dir", entries_c)
    assert fp_a.hash == fp_b.hash == fp_c.hash
    assert fp_a.child_count == fp_b.child_count == fp_c.child_count


def test_fingerprint_different_entries() -> None:
    entries_a = [_entry("a.txt", size=10)]
    entries_b = [_entry("a.txt", size=999)]
    fp_a = generate_fingerprint("/dir", entries_a)
    fp_b = generate_fingerprint("/dir", entries_b)
    assert fp_a.hash != fp_b.hash


def test_fingerprint_empty_directory() -> None:
    fp = generate_fingerprint("/empty", [])
    assert isinstance(fp, DirectoryFingerprint)
    assert fp.path == "/empty"
    assert fp.child_count == 0
    assert isinstance(fp.hash, str) and len(fp.hash) == 64


def test_fingerprint_with_provider_object_id() -> None:
    entries = [
        _entry("a.txt", provider_object_id="obj-1"),
        _entry("b.txt", provider_object_id="obj-2"),
    ]
    fp = generate_fingerprint("/dir", entries)
    assert fp.child_count == 2
    assert isinstance(fp.hash, str) and len(fp.hash) == 64


def test_fingerprint_without_provider_object_id() -> None:
    entries_with = [
        _entry("a.txt", provider_object_id=""),
        _entry("b.txt", provider_object_id=""),
    ]
    entries_without = [_entry("a.txt"), _entry("b.txt")]
    fp_with = generate_fingerprint("/dir", entries_with)
    fp_without = generate_fingerprint("/dir", entries_without)
    assert fp_with.hash == fp_without.hash


def test_child_count_correct() -> None:
    entries = [_entry(f"file-{i}.txt") for i in range(7)]
    fp = generate_fingerprint("/dir", entries)
    assert fp.child_count == 7


def test_fingerprint_is_deterministic() -> None:
    entries = [
        _entry("a.txt", size=10, is_dir=False),
        _entry("sub", is_dir=True, size=0),
    ]
    fp1 = generate_fingerprint("/dir", entries)
    fp2 = generate_fingerprint("/dir", entries)
    assert fp1.hash == fp2.hash
    assert fp1.child_count == fp2.child_count


# =====================================================================
# compare_fingerprints
# =====================================================================

def test_compare_match() -> None:
    entries = [_entry("a.txt"), _entry("b.txt")]
    current = generate_fingerprint("/dir", entries)
    stored = generate_fingerprint("/dir", entries)
    assert compare_fingerprints(current, stored) is True


def test_compare_mismatch() -> None:
    current = generate_fingerprint("/dir", [_entry("a.txt", size=10)])
    stored = generate_fingerprint("/dir", [_entry("a.txt", size=20)])
    assert compare_fingerprints(current, stored) is False
