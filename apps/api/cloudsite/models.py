from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import IndexBase, StateBase
from .modules.identity.infrastructure.models import (
    FolderIdentity,
    FolderIdentityHistory,
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
)
from .modules.resources.infrastructure.models import DownloadRateLimit, Folder, Resource
from .modules.providers.infrastructure.models import (
    AListConnection,
    ContentRootMapping,
    ProviderSyncState,
)
from .modules.delivery.infrastructure.models import (
    DownloadDiagnostic,
    DownloadEvent,
)
from .modules.notifications.infrastructure.models import Notification
from .modules.indexing.infrastructure.legacy_models import (
    FolderScanState,
    SyncChange,
    SyncCycle,
    SyncCycleItem,
    SyncRootResult,
    SyncRun,
)
from .modules.automation.infrastructure.models import CatalogSuggestion, ParserCandidateTask
from .modules.collections.infrastructure.models import Collection, CollectionItem
from .modules.users.infrastructure.models import (
    User,
    UserFavorite,
    UserPlaybackProgress,
    UserResourceHistory,
    UserSession,
)
from .modules.submissions.infrastructure.models import Submission
from .modules.shares.infrastructure.models import Share, ShareVerifyAttempt
from .modules.presentation.infrastructure.models import (
    SitePresentation,
    SitePresentationRevision,
)
from .modules.setup.infrastructure.models import SetupWizardState
from .modules.site.infrastructure.models import SiteSettings
from .modules.catalog.infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogFavorite,
    CatalogLocation,
    CatalogRelation,
    CatalogRelease,
    CatalogReleaseNotification,
    CatalogRevision,
    CatalogSearchOutbox,
    CatalogSubscription,
    CatalogTag,
    CatalogTagAssignment,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemSetting(StateBase):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    value_type: Mapped[str] = mapped_column(String(20), default="string")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OperationLog(StateBase):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    module: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    principal: Mapped[str] = mapped_column(String(200), default="")
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminSession(StateBase):
    __tablename__ = "admin_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    principal: Mapped[str] = mapped_column(String(200), index=True)
    authority: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revocation_reason: Mapped[str] = mapped_column(String(40), default="")
    epoch: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CatalogSearchProjectionState(IndexBase):
    """index.db 端的投影水位：记录每个 entry 已投影到的 catalog revision。

    与 catalog_search_fts 在同一 index 事务写入，保证 FTS 与水位原子推进。
    消费者据此跳过已应用或更旧的 outbox 行，实现崩溃重放幂等与旧不覆盖新。
    """
    __tablename__ = "catalog_search_projection_state"
    entry_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    applied_revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class HealthCheckState(StateBase):
    """M6 健康检查组件状态：每组件一行（component 唯一）。

    component 为 database/alist/storage，status 为 healthy/degraded/unhealthy。
    /api/ready 就绪探针检查后更新对应行；last_error 记录最近一次错误信息。
    """

    __tablename__ = "health_check_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    component: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    last_check_at: Mapped[str] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

class QualityTodo(StateBase):
    """A4 内容质量待办项：将缺说明、失效位置、旧版待复核、疑似重复、
    无结果查询等变为可处理队列。

    每行记录一条检测到的质量问题或用户反馈。todo_type 标识问题类别，
    target_type/target_id 指向受影响实体。status 在 open → dismissed/resolved/wontfix
    间流转。source 区分自动检测与用户反馈。相同 (todo_type, target_type, target_id)
    的 open 项幂等：重复检测不堆积，只更新 detail_json 与 updated_at。
    detail_json 存储四种状态检查结果（file_exists/download_ready/preview_ready/
    content_reviewed）及其他结构化详情。隐藏资源不出现在无权限的队列中。
    """

    __tablename__ = "quality_todos"
    todo_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    todo_type: Mapped[str] = mapped_column(String(30), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    title: Mapped[str] = mapped_column(String(200))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    source: Mapped[str] = mapped_column(String(20), default="auto_detection")
    detection_run_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    dismissed_by: Mapped[str] = mapped_column(String(100), default="")
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismiss_reason: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index(
            "ux_quality_todos_open_dedup",
            "todo_type",
            "target_type",
            "target_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
        Index(
            "ix_quality_todos_type_status",
            "todo_type",
            "status",
        ),
        CheckConstraint(
            "todo_type IN ('missing_description', 'stale_location', 'old_version_review', "
            "'source_conflict', 'suspected_duplicate', 'no_result_query')",
            name="ck_quality_todos_type",
        ),
        CheckConstraint(
            "status IN ('open', 'dismissed', 'resolved', 'wontfix')",
            name="ck_quality_todos_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_quality_todos_severity",
        ),
        CheckConstraint(
            "source IN ('auto_detection', 'user_feedback')",
            name="ck_quality_todos_source",
        ),
    )


class QualityDetectionRun(StateBase):
    """A4 检测运行记录：跟踪每次批量检测的预算消耗与发现数量。

    用于控制检测预算（budget_ms/actual_ms）和幂等性。status 为 running/completed/timeout。
    items_found 为新发现的待办项数，items_deduplicated 为因幂等约束跳过的重复数。
    """

    __tablename__ = "quality_detection_runs"
    run_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_deduplicated: Mapped[int] = mapped_column(Integer, default=0)
    budget_ms: Mapped[int] = mapped_column(Integer, default=5000)
    actual_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'timeout')",
            name="ck_quality_detection_runs_status",
        ),
    )


class SearchQueryLog(StateBase):
    """A4 搜索查询日志：记录查询词与结果数，用于无结果查询聚合。

    每次资源搜索写入一行，不设唯一约束（允许重复查询堆积）。
    检测时按 query 聚合 result_count=0 的行，生成 no_result_query 待办。
    user_id 为发起搜索的用户，nullable 允许匿名搜索日志。
    """

    __tablename__ = "search_query_logs"
    log_id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(200), index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    content_type_filter: Mapped[str | None] = mapped_column(String(40), nullable=True)
    platform_filter: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentFeedback(StateBase):
    """A4 用户内容反馈：用户报告资源条目/交付物/位置的问题。

    feedback_kind 标识问题类别（broken_link/wrong_info/missing_content/other）。
    status 在 pending → reviewed/resolved 间流转。提交反馈时自动创建一条
    source='user_feedback' 的 QualityTodo，管理员处理反馈后同步更新关联待办。
    description 限 1000 字符，admin_note 记录管理员处理备注。
    """

    __tablename__ = "content_feedback"
    feedback_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    feedback_kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    todo_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('entry', 'asset', 'location')",
            name="ck_content_feedback_target_type",
        ),
        CheckConstraint(
            "feedback_kind IN ('broken_link', 'wrong_info', 'missing_content', 'other')",
            name="ck_content_feedback_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'reviewed', 'resolved')",
            name="ck_content_feedback_status",
        ),
    )

class AIProviderConfig(StateBase):
    """A3 AI 提供方配置：管理员配置本地或远程 AI 服务。

    provider_type 标识提供方类型（local_ollama/openai_compatible/custom）。
    api_key_encrypted 存储加密后的 API key（远程服务用）。enabled 默认 False，
    管理员显式启用后才能用于生成。daily_budget_tokens/requests 控制每日用量，
    timeout_seconds/max_retries 控制单次请求行为。关闭 AI 后核心功能不受影响。
    """

    __tablename__ = "ai_provider_configs"
    config_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(30))
    display_name: Mapped[str] = mapped_column(String(100))
    endpoint_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(100), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    daily_budget_tokens: Mapped[int] = mapped_column(Integer, default=100000)
    daily_budget_requests: Mapped[int] = mapped_column(Integer, default=100)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('local_ollama', 'openai_compatible', 'custom')",
            name="ck_ai_provider_config_type",
        ),
    )


class AIGenerationDraft(StateBase):
    """A3 AI 生成草稿：AI 为资源条目生成的简介/标签/别名/用途草稿。

    与 CatalogSuggestion 分表：A2 来源于规则解析，A3 来源于 AI 生成。
    输出保留 provider_type/model_name/prompt_template_version/source_pointers_json
    用于追溯。candidate_status 在 pending → accepted/rejected/modified 间流转。
    accepted 草稿写入正式 catalog 内容并记录修订。input_material_hash 用于幂等：
    相同输入不重复生成 pending 草稿。不将猜测的许可证/作者/版本直接写为已验证事实。
    """

    __tablename__ = "ai_generation_drafts"
    draft_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    field_type: Mapped[str] = mapped_column(String(20), index=True)
    provider_type: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(100), default="")
    prompt_template_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    source_pointers_json: Mapped[str] = mapped_column(Text, default="[]")
    generated_content: Mapped[str] = mapped_column(Text, default="")
    candidate_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    input_material_hash: Mapped[str] = mapped_column(String(64), index=True)
    config_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index(
            "ux_ai_drafts_pending_dedup",
            "target_type",
            "target_id",
            "field_type",
            "input_material_hash",
            unique=True,
            sqlite_where=text("candidate_status = 'pending'"),
        ),
        Index(
            "ix_ai_drafts_target_field",
            "target_id",
            "field_type",
        ),
        CheckConstraint(
            "target_type = 'entry'",
            name="ck_ai_draft_target_type",
        ),
        CheckConstraint(
            "field_type IN ('summary', 'tags', 'aliases', 'usage_note')",
            name="ck_ai_draft_field_type",
        ),
        CheckConstraint(
            "candidate_status IN ('pending', 'accepted', 'rejected', 'modified')",
            name="ck_ai_draft_status",
        ),
    )


class AIBudgetUsage(StateBase):
    """A3 AI 预算用量：按 config_id + date 记录每日 token 和请求消耗。

    每行记录一个 provider config 在某一天的累计用量。生成前检查是否超预算，
    生成后更新用量。date 为 YYYY-MM-DD 字符串。
    """

    __tablename__ = "ai_budget_usage"
    usage_id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[str] = mapped_column(String(35), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("config_id", "date", name="ux_ai_budget_usage_config_date"),
    )

class MetricEvent(StateBase):
    """G2 指标事件：统一事件追踪表。

    记录 download_redirect_issued、search_performed、resource_selected、
    site_setup_completed 等事件。event_data 为 JSON 文本，可能含查询
    等敏感信息，默认不集中上传。retention 由 metrics_retention_days 控制。
    """

    __tablename__ = "metric_events"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_data: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MetricBaseline(StateBase):
    """G2 指标基线：为对比而快照的某时段聚合指标。

    G2a 上线前采集基线，G2b 上线后用相同口径比较。
    summary_json 为 JSON 文本，包含所有 metric_type → value 的映射。
    """

    __tablename__ = "metric_baselines"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricSummary(StateBase):
    """G2 指标聚合：某时段某 metric_type 的聚合值。

    metric_type 包括 resource_selection_success_rate、organize_time_per_100、
    search_hit_rate、no_result_handling、first_site_setup_time、
    update_revisit_rate、support_cost 等。
    """

    __tablename__ = "metric_summaries"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metric_type: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class DeliveryPackage(StateBase):
    """T2 交付包：版本明确的客户交付清单快照。

    保存名称、项目说明、修订、选定的 asset_id/file_id 清单、有效期和发布记录。
    首版只做交付清单快照，新增版本不改变已发布交付包。
    """

    __tablename__ = "delivery_packages"
    package_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    project_note: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    creator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DeliveryPackageItem(StateBase):
    """T2 交付包清单项：每项记录绑定时可靠内容指纹或上游对象版本。

    下载前检测到变化时禁止静默按旧版本交付，提示复核。
    """

    __tablename__ = "delivery_package_items"
    item_id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("delivery_packages.package_id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    bound_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bound_checksum_algorithm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bound_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("package_id", "asset_id", name="ux_delivery_items_package_asset"),
        UniqueConstraint("package_id", "resource_id", name="ux_delivery_items_package_resource"),
    )

class APIToken(StateBase):
    """X2 API 访问令牌：限定动作和对象范围，可撤销。

    token_hash 存储 SHA-256 哈希，不存明文。scopes 为 JSON 数组，
    如 ["entry:read", "entry:write", "release:publish"]。
    """

    __tablename__ = "api_tokens"
    token_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    scopes: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookEndpoint(StateBase):
    """X2 Webhook 端点：签名、重试、事件 ID、去重和失败队列。

    event_types 为 JSON 数组，如 ["entry.created", "release.published"]。
    secret 用于 HMAC-SHA256 签名验证。
    """

    __tablename__ = "webhook_endpoints"
    endpoint_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(128), default="")
    event_types: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookDelivery(StateBase):
    """X2 Webhook 投递记录：事件 ID 去重、重试、失败队列。

    status: pending/delivered/failed
    event_id 用于幂等去重：同一 event_id 不重复投递。
    """

    __tablename__ = "webhook_deliveries"
    delivery_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("webhook_endpoints.endpoint_id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class ProviderCompatRecord(StateBase):
    """X1 Provider 兼容测试记录：每个平台/版本的适配器兼容性结果。

    验收：所有支持平台有实际兼容记录。
    """

    __tablename__ = "provider_compat_records"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(40), index=True)
    adapter_version: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(100), index=True)
    platform_version: Mapped[str] = mapped_column(String(100), default="")
    test_result: Mapped[str] = mapped_column(String(20), default="pass", index=True)
    tested_capabilities_json: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CloudDownloadTask(StateBase):
    """CloudSite 115 cloud download submission state.

    Persisted schema is intentionally minimal: only the owning user, an
    optional driver hash, lifecycle status, and a short display name are
    stored. Submitted URLs and credentials are never persisted in this
    table. driver_hash is not unique because multiple users may submit
    the same driver hash.
    """

    __tablename__ = "cloud_download_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    driver_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
