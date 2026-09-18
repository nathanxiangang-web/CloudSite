"""Indexing engine switch.

When CLOUDSITE_INDEXING_ENGINE=v2, uses the new modules/indexing
ScanCategoryService + ReconcileService. When v1 (default), delegates
to the legacy sync/rolling.py.
"""
from __future__ import annotations

import os


def get_indexing_engine() -> str:
    from cloudsite.config import settings
    return settings.indexing_engine


def use_indexing_v2() -> bool:
    return get_indexing_engine() == "v2"


__all__ = ["get_indexing_engine", "use_indexing_v2"]