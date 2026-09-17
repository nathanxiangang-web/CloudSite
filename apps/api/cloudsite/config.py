from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    secret_key: str = ""
    master_key: str = ""
    setup_token: str = ""
    allow_insecure_dev_key: bool = False
    cors_origins: str = "http://localhost:3000"
    trusted_proxy_cidrs: str = "127.0.0.1/32,::1/128,172.16.0.0/12"
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
    sync_missing_confirm_runs: int = 2
    sync_mass_change_min_items: int = 100
    sync_mass_change_ratio: float = 0.10
    sync_max_item_attempts: int = 6

    # C7: 索引引擎切换开关。默认 "v1" 使用 sync/rolling.py 旧索引；
    # 设为 "v2" 时改用 modules/indexing 的 ScanCategoryService + ReconcileService。
    # 环境变量 CLOUDSITE_INDEXING_ENGINE 控制。
    indexing_engine: str = "v1"

    # C9: 独立 Worker 进程配置。Worker 从 DB 队列租约并执行任务，
    # 与 API 进程解耦。环境变量 CLOUDSITE_WORKER_* 控制。
    worker_queue: str = "default"
    worker_poll_interval: float = 2.0
    worker_max_concurrent: int = 4

    # Set exactly one existing CloudSite user ID before enabling automatic
    # organization. Zero disables user-controlled organization actions.
    organizer_user_id: int = 0
    organizer_move_enabled: bool = False

    # Non-secret administrator session epoch. Later login/middleware code compares
    # AdminSession.epoch against this value and rejects sessions with an older epoch.
    # Increment during security upgrades or administrator rebind to invalidate all
    # existing administrator sessions without rotating secrets. Default 1.
    admin_session_epoch: int = 1

    # D2: 启动时幂等注入默认任务型专题种子（生产默认开启，测试在 conftest 关闭）。
    seed_default_collections: bool = True

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
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("CLOUDSITE_CORS_ORIGINS 使用凭据认证时不能包含通配符 '*'")
        return origins

    @property
    def trusted_proxy_cidr_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxy_cidrs.split(",") if item.strip()]

    @property
    def credential_key(self) -> str:
        """Dedicated credential key with a backwards-compatible fallback."""
        return self.master_key or self.secret_key


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
