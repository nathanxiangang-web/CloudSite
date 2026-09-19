"""Resources preview service regression tests."""

from pathlib import Path

import pytest

from cloudsite.modules.providers.domain.runtime import (
    ProviderAccessError,
    ProviderUnavailableError,
)
from cloudsite.modules.resources.application import preview_service as preview_mod
from cloudsite.modules.resources.application.preview_service import (
    ResourcePreviewService,
)
from cloudsite.modules.resources.domain.errors import ResourceNotFoundError
from cloudsite.modules.resources.domain.preview import ResourcePreviewError
from cloudsite.modules.resources.domain.views import ResourcePreviewView


class FakeQueries:
    def __init__(self, resource=None, error=None):
        self.resource = resource
        self.error = error

    async def preview_resource(self, *, resource_id, enabled_root_ids):
        if self.error:
            raise self.error
        return self.resource


class FakeProvider:
    def __init__(self, *, url="https://storage.example/file", error=None):
        self.url = url
        self.error = error
        self.calls = []

    async def download_entry(self, *, root_mapping_id, path):
        self.calls.append((root_mapping_id, path))
        if self.error:
            raise self.error
        from cloudsite.modules.providers.domain.runtime import ProviderEntry
        return ProviderEntry(
            url=self.url,
            host="storage.example",
            base_path="/",
            has_sign=False,
        )

    async def preview_entry(self, *, root_mapping_id, path):
        raise AssertionError("preview_entry is not used by Resources preview cache")


def _resource(*, extension="txt", mime_type="text/plain", size=5):
    return ResourcePreviewView(
        id="r_preview",
        name=f"preview.{extension}",
        path=f"/docs/preview.{extension}",
        root_mapping_id=11,
        extension=extension,
        mime_type=mime_type,
        size=size,
        status="active",
    )


async def test_text_preview_cache_hit_does_not_touch_provider(monkeypatch, tmp_path):
    resource = _resource()
    cached = tmp_path / "r_preview.txt"
    cached.write_text("hello", encoding="utf-8")
    provider = FakeProvider()

    monkeypatch.setattr(
        preview_mod,
        "fresh_preview_cache_path",
        lambda _resource: cached,
    )

    service = ResourcePreviewService(FakeQueries(resource), provider)
    result = await service.text_preview(
        resource_id=resource.id,
        enabled_root_ids={11},
    )

    assert result["content"] == "hello"
    assert result["preview_type"] == "text"
    assert provider.calls == []


async def test_preview_cache_miss_uses_provider_runtime(monkeypatch, tmp_path):
    resource = _resource()
    cached = tmp_path / "r_preview.txt"
    cached.write_text("from-provider", encoding="utf-8")
    provider = FakeProvider(url="https://storage.example/raw.txt")
    captured = {}

    monkeypatch.setattr(
        preview_mod,
        "fresh_preview_cache_path",
        lambda _resource: None,
    )

    async def fake_cache(res, url):
        captured["resource"] = res
        captured["url"] = url
        return cached

    monkeypatch.setattr(preview_mod, "cache_preview_from_url", fake_cache)

    service = ResourcePreviewService(FakeQueries(resource), provider)
    result = await service.text_preview(
        resource_id=resource.id,
        enabled_root_ids={11},
    )

    assert result["content"] == "from-provider"
    assert provider.calls == [(11, "/docs/preview.txt")]
    assert captured["url"] == "https://storage.example/raw.txt"


@pytest.mark.parametrize(
    ("provider_error", "expected_code"),
    [
        (ProviderUnavailableError("offline"), "PV-005"),
        (ProviderAccessError("provider failed"), "PV-003"),
    ],
)
async def test_provider_failures_preserve_preview_error_mapping(
    monkeypatch,
    provider_error,
    expected_code,
):
    resource = _resource(extension="pdf", mime_type="application/pdf")
    provider = FakeProvider(error=provider_error)
    monkeypatch.setattr(
        preview_mod,
        "fresh_preview_cache_path",
        lambda _resource: None,
    )

    service = ResourcePreviewService(FakeQueries(resource), provider)
    with pytest.raises(ResourcePreviewError) as raised:
        await service.cached_preview_url(
            resource_id=resource.id,
            enabled_root_ids={11},
            expected_type="pdf",
        )

    assert raised.value.code == expected_code
    assert raised.value.status_code == 503


async def test_cached_preview_url_keeps_existing_ticket_shape(monkeypatch, tmp_path):
    resource = _resource(extension="pdf", mime_type="application/pdf")
    cached = tmp_path / "r_preview.pdf"
    cached.write_bytes(b"%PDF")
    provider = FakeProvider()

    monkeypatch.setattr(
        preview_mod,
        "fresh_preview_cache_path",
        lambda _resource: cached,
    )
    monkeypatch.setattr(
        preview_mod,
        "create_preview_ticket",
        lambda resource_id: f"ticket-{resource_id}",
    )

    service = ResourcePreviewService(FakeQueries(resource), provider)
    url = await service.cached_preview_url(
        resource_id=resource.id,
        enabled_root_ids={11},
        expected_type="pdf",
    )

    assert url == "/office-files/r_preview.pdf?ticket=ticket-r_preview"
    assert provider.calls == []


async def test_query_visibility_errors_still_map_to_pv001():
    service = ResourcePreviewService(
        FakeQueries(error=ResourceNotFoundError("missing")),
        FakeProvider(),
    )

    with pytest.raises(ResourcePreviewError) as raised:
        await service.capability(
            resource_id="missing",
            enabled_root_ids={11},
        )

    assert raised.value.code == "PV-001"
    assert raised.value.status_code == 404
