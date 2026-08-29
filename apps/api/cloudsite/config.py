from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    secret_key: str = "cloudsite-development-key-change-me"
    master_key: str = ""
    cors_origins: str = "http://localhost:3000"
    request_timeout_seconds: float = 20.0
    download_cache_ttl_seconds: int = 60
    download_cache_max_entries: int = 500
    preview_cache_ttl_seconds: int = 60
    preview_cache_max_entries: int = 500
    text_preview_max_bytes: int = 1048576
    office_cache_ttl_seconds: int = 3600
    office_cache_max_bytes: int = 200 * 1024 * 1024
    sync_list_rps: float = 2.0
    sync_list_jitter_ms: int = 250
    sync_manual_cooldown_seconds: int = 300
    sync_startup_delay_min_seconds: int = 30
    sync_startup_delay_max_seconds: int = 60
    sync_failure_retry_delay_seconds: int = 900
    sync_missing_confirm_runs: int = 1
    sync_mass_change_min_items: int = 100
    sync_mass_change_ratio: float = 0.10

    model_config = SettingsConfigDict(env_prefix="CLOUDSITE_", env_file=".env", extra="ignore")

    @property
    def office_cache_dir(self) -> Path:
        return self.data_dir / "office-cache"

    @property
    def state_db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'state.db'}"

    @property
    def index_db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'index.db'}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def credential_key(self) -> str:
        """Dedicated credential key with a backwards-compatible fallback."""
        return self.master_key or self.secret_key


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
