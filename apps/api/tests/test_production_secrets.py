import pytest

from cloudsite.config import settings
from cloudsite.infrastructure.security import validate_production_secrets


def test_production_secret_rejects_short_key(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev_key", False)
    monkeypatch.setattr(settings, "secret_key", "too-short")
    monkeypatch.setattr(settings, "master_key", "")

    with pytest.raises(RuntimeError, match="长度不足 32"):
        validate_production_secrets()


def test_production_secret_accepts_long_random_key(monkeypatch):
    monkeypatch.setattr(settings, "allow_insecure_dev_key", False)
    monkeypatch.setattr(
        settings,
        "secret_key",
        "ci-production-secret-key-0123456789abcdef0123456789abcdef",
    )
    monkeypatch.setattr(settings, "master_key", "")

    validate_production_secrets()
