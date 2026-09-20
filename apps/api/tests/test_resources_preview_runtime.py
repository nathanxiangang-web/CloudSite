"""Preview/provider runtime boundary regression tests."""

from types import SimpleNamespace

import pytest

from cloudsite import office, preview
from cloudsite.modules.providers.contracts.public import (
    ProviderAccessError,
    ProviderEntry,
    ProviderUnavailableError,
)


def _resource(**overrides):
    values = {
        "id": "r_preview",
        "name": "manual.pdf",
        "path": "/docs/manual.pdf",
        "root_mapping_id": 7,
        "extension": "pdf",
        "mime_type": "application/pdf",
        "size": 100,
        "status": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_direct_preview_uses_provider_runtime_and_preserves_entry_host():
    calls = []

    class Runtime:
        async def preview_entry(self, *, root_mapping_id, path):
            calls.append((root_mapping_id, path))
            return ProviderEntry(
                url="https://alist.example/d/docs/manual.pdf?sign=x",
                host="alist.example",
                base_path="/docs",
                has_sign=True,
            )

    preview.preview_url_cache.clear()
    resolution = await preview.resolve_preview_url(_resource(), Runtime())

    assert calls == [(7, "/docs/manual.pdf")]
    assert resolution.url.startswith("https://alist.example/d/")
    assert resolution.target_host == "alist.example"
    assert resolution.cache_hit is False


async def test_direct_preview_maps_provider_metadata_failure_without_leak():
    class Runtime:
        async def preview_entry(self, **_kwargs):
            raise ProviderAccessError(
                "metadata",
                "private upstream detail",
                status_code=502,
            )

    preview.preview_url_cache.clear()
    with pytest.raises(preview.PreviewError) as raised:
        await preview.resolve_preview_url(_resource(), Runtime())

    assert raised.value.code == "PV-003"
    assert raised.value.status_code == 502
    assert "private upstream detail" not in raised.value.message


async def test_office_cache_fails_closed_when_provider_unavailable(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setitem(
        office.ensure_preview_cached.__globals__,
        "settings",
        SimpleNamespace(
            office_cache_dir=tmp_path,
            office_cache_ttl_seconds=3600,
            office_cache_max_bytes=1024 * 1024,
        ),
    )

    class Runtime:
        async def download_entry(self, **_kwargs):
            raise ProviderUnavailableError("disabled")

    with pytest.raises(office.OfficePreviewError) as raised:
        await office.ensure_preview_cached(_resource(), Runtime())

    assert raised.value.code == "PV-005"
    assert raised.value.status_code == 503


async def test_office_cache_maps_provider_access_failure_to_preview_error(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setitem(
        office.ensure_preview_cached.__globals__,
        "settings",
        SimpleNamespace(
            office_cache_dir=tmp_path,
            office_cache_ttl_seconds=3600,
            office_cache_max_bytes=1024 * 1024,
        ),
    )

    class Runtime:
        async def download_entry(self, **_kwargs):
            raise ProviderAccessError(
                "authentication",
                "private credential detail",
                status_code=503,
            )

    with pytest.raises(office.OfficePreviewError) as raised:
        await office.ensure_preview_cached(_resource(), Runtime())

    assert raised.value.code == "PV-003"
    assert raised.value.status_code == 503
    assert "private credential detail" not in raised.value.message
