"""Resources preview helper ownership compatibility tests."""

from cloudsite import office as legacy_office
from cloudsite import preview as legacy_preview
from cloudsite.modules.resources.infrastructure import office_preview
from cloudsite.modules.resources.infrastructure import preview as owned_preview


def test_legacy_preview_exports_are_exact_resources_objects():
    assert legacy_preview.PreviewError is owned_preview.PreviewError
    assert legacy_preview.PreviewResolution is owned_preview.PreviewResolution
    assert legacy_preview.preview_capability is owned_preview.preview_capability
    assert legacy_preview.resolve_preview_url is owned_preview.resolve_preview_url
    assert legacy_preview.load_text_preview is owned_preview.load_text_preview
    assert legacy_preview.preview_url_cache is owned_preview.preview_url_cache
    assert legacy_preview.settings is owned_preview.settings


def test_legacy_office_exports_are_exact_resources_objects():
    assert legacy_office.OfficePreviewError is office_preview.OfficePreviewError
    assert legacy_office.ensure_preview_cached is office_preview.ensure_preview_cached
    assert legacy_office.office_cache_filename is office_preview.office_cache_filename
    assert legacy_office.office_cache_path is office_preview.office_cache_path
    assert legacy_office.render_pdf_pages is office_preview.render_pdf_pages
    assert legacy_office.settings is office_preview.settings


def test_preview_helpers_are_owned_by_resources_module():
    assert owned_preview.PreviewError.__module__ == (
        "cloudsite.modules.resources.infrastructure.preview"
    )
    assert office_preview.OfficePreviewError.__module__ == (
        "cloudsite.modules.resources.infrastructure.office_preview"
    )
