"""Delivery provider-runtime download tests."""

from types import SimpleNamespace

import pytest

from cloudsite.modules.delivery.contracts.public import (
    map_provider_error as public_map_provider_error,
)
from cloudsite.modules.delivery.domain.download import (
    DownloadError,
    map_provider_error,
    resolve_download_entry,
)
from cloudsite.modules.providers.contracts.public import (
    ProviderAccessError,
    ProviderEntry,
    ProviderUnavailableError,
)


def _resource():
    return SimpleNamespace(
        id="r_download",
        path="/software/tool.zip",
        root_mapping_id=7,
    )


async def test_download_resolution_uses_provider_runtime_and_preserves_diagnostics():
    calls = []

    class Runtime:
        async def download_entry(self, *, root_mapping_id, path):
            calls.append((root_mapping_id, path))
            return ProviderEntry(
                url="https://alist.example/d/software/tool.zip?sign=x",
                host="alist.example",
                base_path="/software",
                has_sign=True,
            )

    resolution = await resolve_download_entry(_resource(), Runtime())

    assert calls == [(7, "/software/tool.zip")]
    assert resolution.target_host == "alist.example"
    assert resolution.base_path == "/software"
    assert resolution.has_sign is True
    names = [step["name"] for step in resolution.steps]
    assert names == [
        "alist_connection",
        "authentication",
        "alist_file_info",
        "base_path_resolve",
        "download_sign",
        "download_entry_build",
        "redirect_validation",
        "redirect_ready",
    ]


@pytest.mark.parametrize(
    ("exc", "code", "step", "status"),
    [
        (
            ProviderUnavailableError("disabled"),
            "DL-002",
            "alist_connection",
            503,
        ),
        (
            ProviderAccessError("unreachable", "secret", status_code=503),
            "DL-002",
            "alist_connection",
            503,
        ),
        (
            ProviderAccessError("authentication", "secret", status_code=503),
            "DL-006",
            "authentication",
            503,
        ),
        (
            ProviderAccessError("credentials", "secret", status_code=503),
            "DL-006",
            "authentication",
            503,
        ),
        (
            ProviderAccessError("metadata", "secret", status_code=503),
            "DL-003",
            "alist_file_info",
            503,
        ),
        (
            ProviderAccessError("metadata", "secret", status_code=429),
            "DL-003",
            "alist_file_info",
            429,
        ),
        (
            ProviderAccessError("configuration", "secret", status_code=502),
            "DL-999",
            "download_entry",
            502,
        ),
    ],
)
def test_provider_errors_map_to_existing_download_contract(exc, code, step, status):
    mapped = map_provider_error(exc)
    assert mapped.code == code
    assert mapped.failed_step == step
    assert mapped.status_code == status
    assert "secret" not in mapped.message


async def test_resolve_download_entry_never_leaks_provider_error_detail():
    class Runtime:
        async def download_entry(self, **_kwargs):
            raise ProviderAccessError(
                "authentication",
                "private credential detail",
                status_code=503,
            )

    with pytest.raises(DownloadError) as raised:
        await resolve_download_entry(_resource(), Runtime())

    assert raised.value.code == "DL-006"
    assert "private credential detail" not in raised.value.message


def test_delivery_public_contract_exports_provider_error_mapping():
    assert public_map_provider_error is map_provider_error
