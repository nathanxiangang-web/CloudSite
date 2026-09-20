"""Resources rate-limit ownership compatibility tests."""

from cloudsite import download_rate_limit as legacy_rate_limit
from cloudsite.modules.delivery.infrastructure import rate_limit as delivery_facade
from cloudsite.modules.resources.contracts import public as resources_contract
from cloudsite.modules.resources.infrastructure import rate_limit as resources_impl


def test_legacy_and_delivery_rate_limit_exports_are_resources_objects():
    assert legacy_rate_limit.DownloadRateDecision is resources_impl.DownloadRateDecision
    assert legacy_rate_limit.check_download_rate is resources_impl.check_download_rate
    assert legacy_rate_limit.cleanup_download_rate_limits is resources_impl.cleanup_download_rate_limits

    assert delivery_facade.DownloadRateDecision is resources_impl.DownloadRateDecision
    assert delivery_facade.check_download_rate is resources_impl.check_download_rate
    assert delivery_facade.cleanup_download_rate_limits is resources_impl.cleanup_download_rate_limits

    assert resources_contract.DownloadRateDecision is resources_impl.DownloadRateDecision
    assert resources_contract.check_download_rate is resources_impl.check_download_rate


def test_rate_limit_implementation_is_resources_owned():
    assert resources_impl.DownloadRateDecision.__module__ == (
        "cloudsite.modules.resources.infrastructure.rate_limit"
    )
