"""Compatibility facade for Resources-owned Office preview helpers."""

from .modules.resources.infrastructure.office_preview import (
    OFFICE_CONTENT_TYPES,
    OfficePreviewError,
    ensure_preview_cached,
    office_cache_filename,
    office_cache_path,
    office_content_type,
    render_pdf_pages,
    settings,
    sweep_office_cache,
)

__all__ = [
    "OFFICE_CONTENT_TYPES",
    "OfficePreviewError",
    "ensure_preview_cached",
    "office_cache_filename",
    "office_cache_path",
    "office_content_type",
    "render_pdf_pages",
    "settings",
    "sweep_office_cache",
]
