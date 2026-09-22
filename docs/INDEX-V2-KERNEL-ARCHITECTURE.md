# CloudSite Index V2 Kernel Architecture

> 状态：Draft / New Core Baseline
>
> 分支：`design/index-v2-kernel`
>
> 日期：2026-09-22
>
> 定位：CloudSite 核心内核 / P0
>
> 本文档在架构定位上高于现有 `docs/V2后续优化方向开发文档.md`。旧文档继续保留，作为算法、安全门禁、故障注入和验收矩阵的详细参考；本文负责重新定义 Index V2 的内核边界、依赖方向、事实所有权与回退重建方式。

---

# 0. 为什么重新定义

CloudSite 1.0.0 仍然可以工作，而 2.0 在连续重构后出现了明显的结构膨胀和联动故障。

Index V2 本身的方向没有错。现有 V2 文档也已经明确它是 CloudSite 的“核心心脏”，并已经设计了：

- Snapshot；
- bounded concurrent scan；
- Durable Scan；
- Checkpoint / Resume；
- Complete Gate；
- Atomic Reconcile；
- Stable Identity；
- Root Lifecycle；
- Dirty Scope；
- Rolling Verification；
- Full Audit / Repair；
- Change Feed。

真正的问题是：

> 实现层仍然把 Index V2 当成 CloudSite 的一个普通 business module。

当前实现还通过 CloudSite 的 Providers、Resources、Identity、Search、platform/db、platform/tasks、Admin 状态等边界组合运行。这样会导致 Index V2 的正确性依赖 CloudSite 其它模块的演进，CloudSite 其它模块的重构也会反过来影响索引核心。

这不符合核心基础设施的定位。

从现在开始，Index V2 的正式定位改为：

> **Index V2 是 CloudSite 的资源事实内核（Resource Truth Kernel）。CloudSite 是它的宿主和上层应用，而不是它的控制者。**

---

# 1. 核心目标

最终应形成：

```text
                 CloudSite Application
     UI / API / Search / Catalog / Share / Download
                         │
                         │ Query / Events / Commands
                         ▼
               ┌─────────────────────┐
               │   INDEX V2 KERNEL   │
               │  Resource Truth Core │
               └─────────────────────┘
                    ▲             │
                    │             │
           Provider Port      Kernel Storage
                    │             │
                    ▼             ▼
            AList / 115 / ...   SQLite / DB
```

CloudSite 可以替换：

- UI；
- Search；
- Catalog；
- Download；
- API；
- Provider；
- 数据库适配器；

但不能改变 Index Kernel 的核心不变量。

Index Kernel 可以脱离 CloudSite 单独测试，并原则上可以被单独提取为独立 package。

---

# 2. 内核必须拥有的事实

旧设计中 Resources 被定义为 authoritative Folder/Resource persistence。

新的内核级设计调整为：

> **Index Kernel Canonical Inventory 才是 Provider 资源事实的唯一权威来源。**

Index Kernel 必须拥有：

1. Root 生命周期；
2. Canonical Folder / Resource Inventory；
3. Stable Identity；
4. Scan Run；
5. Durable Directory Queue；
6. Staging Entries；
7. Reconcile；
8. Change Journal；
9. Dirty Scope；
10. Verification State；
11. Audit State；
12. Generation / Baseline；
13. Cursor / Provider Revision；
14. 数据安全 Guard；
15. Crash Recovery 状态。

CloudSite 的 `resources`、`search`、`catalog` 等都改成：

> 内核事实的查询层或投影层。

不再允许业务模块拥有另一份“同级事实”。

---

# 3. 依赖方向必须单向

正式依赖方向：

```text
CloudSite
  │
  ├── calls Kernel Command API
  ├── reads Kernel Query API
  └── consumes Kernel Change Feed
          │
          ▼
      Index Kernel
          │
          ├── ProviderPort
          ├── KernelStorePort
          ├── ClockPort
          └── EventSinkPort
```

禁止：

```text
Index Kernel
    ↓
CloudSite Search
CloudSite Catalog
CloudSite Admin
CloudSite FastAPI
CloudSite ORM Models
CloudSite main.py
CloudSite tasking
CloudSite UI status
```

Kernel 不知道 CloudSite 有 Search、Catalog、Share、Download。

它只知道：

```text
Provider
Inventory
Identity
Change
Root
Run
Checkpoint
Audit
```

---

# 4. 内核硬边界

Index Kernel Core 禁止直接 import：

```text
cloudsite.main
cloudsite.routers.*
cloudsite.modules.search.*
cloudsite.modules.catalog.*
cloudsite.modules.collections.*
cloudsite.modules.delivery.*
cloudsite.modules.automation.*
cloudsite.modules.resources.*
cloudsite.modules.identity.*
cloudsite.modules.providers.*
cloudsite.platform.tasks.*
FastAPI
Web UI
```

Kernel Core 也不能：

- 读取环境变量；
- 自己创建 HTTP API；
- 写 Admin UI 状态；
- 直接 rebuild Search；
- 直接写 Catalog；
- 直接操作 Share / Favorite / Playback；
- 依赖 CloudSite 全局 session；
- 依赖 CloudSite 的 ORM Entity。

宿主通过明确 Port 注入能力。

---

# 5. Kernel 分层

推荐目录：

```text
apps/api/cloudsite/index_kernel/
├── __init__.py
│
├── domain/
│   ├── root.py
│   ├── inventory.py
│   ├── identity.py
│   ├── snapshot.py
│   ├── change.py
│   ├── dirty_scope.py
│   ├── verification.py
│   ├── audit.py
│   └── errors.py
│
├── ports/
│   ├── provider.py
│   ├── store.py
│   ├── clock.py
│   └── events.py
│
├── engine/
│   ├── lifecycle.py
│   ├── bootstrap.py
│   ├── scanner.py
│   ├── durable_scan.py
│   ├── reconcile.py
│   ├── identity_engine.py
│   ├── incremental.py
│   ├── verification.py
│   ├── audit.py
│   └── recovery.py
│
├── runtime/
│   ├── kernel.py
│   ├── coordinator.py
│   └── status.py
│
├── storage/
│   └── sqlite/
│       ├── schema.py
│       ├── store.py
│       └── migrations.py
│
└── tests/
    ├── unit/
    ├── contract/
    ├── fault/
    └── e2e/
```

宿主适配层：

```text
apps/api/cloudsite/integrations/indexing/
├── alist_provider.py
├── cloudsite_projection.py
├── search_projection.py
├── admin_status.py
└── scheduler.py
```

AList 是宿主 Provider Adapter，不进入 Kernel Domain。

---

# 6. Kernel 对外接口

Kernel 对外只保留三类 API。

## 6.1 Commands

```python
bootstrap_root(root_id)
resume_root(root_id)
run_cycle(root_id)
verify_root(root_id, budget)
audit_root(root_id)
repair_root(root_id, plan)
rebuild_root(root_id)
cancel_run(run_id)
record_known_change(root_id, change)
```

## 6.2 Queries

```python
get_root_state(root_id)
get_run_status(run_id)
get_inventory_item(resource_id)
list_inventory(root_id, ...)
list_changes(after_seq, ...)
list_dirty_scopes(root_id)
get_health()
```

## 6.3 Provider Port

```python
class ProviderPort(Protocol):
    async def list_directory(self, root, path, *, cursor=None): ...
    async def inspect(self, root, object_ref): ...
    async def capabilities(self, root): ...
    async def fetch_changes(self, root, cursor): ...
```

Provider 能力不足时，Kernel 自己选择 fallback 策略。

CloudSite 不应该在外部拼接扫描算法。

---

# 7. KernelStorePort

Kernel 必须通过自己的统一 Store Port 操作所有核心事实。

建议最小能力：

```text
RootStateRepository
RunRepository
ScanQueueRepository
StagingRepository
InventoryRepository
IdentityRepository
ChangeJournalRepository
DirtyScopeRepository
VerificationRepository
AuditRepository
```

第一阶段可以只有 SQLite 实现。

但 Domain / Engine 不 import SQLAlchemy model。

这样未来数据库替换不会重写扫描与 Reconcile。

---

# 8. Canonical Inventory

新的正式事实表建议使用独立命名：

```text
index_kernel_roots
index_kernel_folders
index_kernel_resources
index_kernel_identity_history
index_kernel_changes

index_kernel_scan_runs
index_kernel_scan_dirs
index_kernel_staging_entries

index_kernel_dirty_scopes
index_kernel_verification
index_kernel_audit_runs
```

CloudSite 原有 `folders/resources` 在重建阶段有两种选择：

### 方案 A：直接迁移为 Kernel Inventory

适用于新 2.0 基线。

### 方案 B：保留作为兼容 Projection

适用于从 1.0.0 平滑迁移。

优先推荐 B 起步，等 Kernel 稳定后再决定是否物理合并。

关键原则：

> 逻辑事实只允许一份。

---

# 9. Root 是内核一级对象

每个 Root 独立拥有生命周期：

```text
uninitialized
bootstrap_required
bootstrapping
resume_required
ready
verifying
degraded
audit_required
rebuild_required
disabled
```

Root State 至少：

```text
root_id
provider_key
provider_root_ref

status
generation

bootstrap_completed_at
last_change_at
last_verified_at
last_audit_at
last_reconcile_at

provider_cursor
provider_revision
scan_fingerprint

active_run_id

last_error_code
last_error_message

created_at
updated_at
```

Root 生命周期由 Kernel 决定。

Scheduler 只调用：

```text
kernel.run_cycle(root_id)
```

不能由 Scheduler 自己判断该 Full Scan 还是 Verification。

---

# 10. 正式运行状态机

```text
UNINITIALIZED
      │
      ▼
BOOTSTRAP_REQUIRED
      │
      ▼
BOOTSTRAPPING ─── crash ───▶ RESUME_REQUIRED
      │                         │
      │ complete                │ resume
      ▼                         ▼
     READY ◀────────────────────┘
      │
      ├── known change ───────▶ incremental apply
      │
      ├── verification ───────▶ VERIFYING
      │                           │
      │                           ├── clean ──▶ READY
      │                           └── drift ──▶ DIRTY SCOPE
      │
      ├── serious drift ──────▶ AUDIT_REQUIRED
      │
      ├── provider failure ───▶ DEGRADED
      │
      └── baseline invalid ───▶ REBUILD_REQUIRED
```

READY 是长期默认态。

READY 不允许默认周期性全 Root Full Scan。

---

# 11. Bootstrap

Bootstrap 只负责建立第一份可信事实。

```text
create generation
→ create scan run
→ bounded scan
→ durable checkpoints
→ persistent staging
→ complete gate
→ identity resolve
→ reconcile
→ commit canonical inventory
→ append change journal
→ mark baseline
→ READY
```

Bootstrap 结束前：

> Canonical Inventory 不能被半成品覆盖。

---

# 12. Bounded Concurrent Scanner

Kernel Scanner 使用：

```text
asyncio.Queue
+ bounded workers
```

建议默认：

```text
per-root directory workers = 8
global provider requests = 16
reconcile writer = 1
```

但参数必须属于 Kernel Runtime Config，不属于 Web UI 业务配置。

要求：

- 结果与 concurrency=1 完全一致；
- 不依赖遍历顺序；
- 无 duplicate dir；
- 无 lost child；
- 无无限 gather；
- Provider backpressure 可生效。

---

# 13. Durable Scan

Scan 必须是可恢复作业，而不是一次 Python 函数调用。

核心表：

```text
index_kernel_scan_runs
index_kernel_scan_dirs
index_kernel_staging_entries
```

目录 checkpoint 原子事务：

```text
BEGIN

save entries
enqueue child dirs
mark current dir done
update run counters

COMMIT
```

硬规则：

> current dir 不能在 children / entries 持久化前进入 done。

---

# 14. Crash Recovery

任意时间进程退出后：

```text
running dir → pending
running run → resume_required
```

恢复必须满足：

- done dir 不重新请求；
- staging 不丢；
- resource identity 不漂移；
- final inventory 与 clean scan 一致；
- reconcile 已完成则不重复 destructive commit；
- reconcile 未完成则可从 staging 重试。

---

# 15. Complete Gate

只有：

```text
pending = 0
running = 0
failed = 0
pagination_complete = true
provider_state_known = true
```

才允许：

```text
snapshot_complete = true
```

只有 complete snapshot 才有资格推导 removal。

这条属于 Kernel invariant，宿主不能关闭。

---

# 16. Removal Safety

以下任意情况：

```text
provider timeout
permission denied
root missing
malformed response
pagination incomplete
failed directory
unknown provider state
unexpected inventory shrink
```

默认：

```text
NO DESTRUCTIVE REMOVAL
```

需要额外 Guard：

```text
unexpected removal ratio
abnormal shrink
root identity mismatch
provider permission change
```

Guard 触发后：

```text
root → degraded / audit_required
```

而不是“扫描不到 = 删除”。

---

# 17. Stable Identity 内核化

Stable Identity 不再作为外部业务模块决定 Index Kernel 的资源 ID。

Kernel 必须自己拥有：

```text
provider stable id
identity history
fingerprint matching
rename/move matching
conflict detection
```

匹配优先级：

```text
provider stable object id
    ↓
identity history
    ↓
strong fingerprint
    ↓
safe structural matching
    ↓
new identity
```

无法唯一确认：

```text
CONFLICT
```

禁止猜。

必须证明：

```text
rename → same resource_id
move → same resource_id
folder rename → descendants remain valid
restart → same IDs
concurrency change → same IDs
```

---

# 18. Atomic Reconcile

Reconcile 的正式语义：

```text
Complete Staging
    ↓
Identity Resolve
    ↓
Diff
    ↓
Safety Guards
    ↓
ONE ROOT TRANSACTION
    ↓
Canonical Inventory
    ↓
Change Journal
    ↓
Commit
```

失败：

```text
ROLLBACK
```

Staging 保留。

Production Inventory 保持上一代可信事实。

---

# 19. Change Journal

Kernel 不直接通知 Search/Catalog 如何处理。

Kernel 只生成稳定、可重放的 Change Journal。

变化类型：

```text
added
updated
renamed
moved
removed
identity_conflict
root_state_changed
```

Change 至少包含：

```text
seq
generation
root_id
resource_id
change_type
before
after
committed_at
```

上层消费者用自己的 offset 消费。

这使：

- Search 挂掉不会影响 Kernel；
- Catalog 挂掉不会影响 Kernel；
- 消费者可以 replay；
- 不需要 Kernel import 上层模块。

---

# 20. Search 必须彻底降级为 Projection

正式关系：

```text
Index Kernel
   │
   └── Change Journal
           │
           ▼
        Search
```

如果 Search 更新失败：

```text
Kernel Inventory = committed
Search = dirty
```

然后 Search 自己 replay / rebuild。

绝对禁止：

> Search 失败导致 Kernel Reconcile rollback。

---

# 21. Incremental

Incremental 不是必须依赖 Provider 原生 Delta。

统一输入：

```text
ProviderChange
```

来源：

```text
known_cloudsite_change
provider_delta
provider_webhook
verification
manual
```

Generic AList 无可靠 change feed 时：

```text
Known Changes
+ Rolling Verification
+ Dirty Scope
+ Rare Full Audit
```

不允许伪装成 native delta。

---

# 22. Dirty Scope

Dirty Scope 是 Kernel 自有持久状态。

```text
root_id
path
reason
priority
status
attempts
detected_at
updated_at
```

合并原则：

- 父目录 dirty 时不重复插入子目录；
- 大量兄弟 dirty 可按明确阈值提升父目录；
- promotion 必须 deterministic；
- 服务重启后 dirty scope 不丢。

---

# 23. Rolling Verification

Verification 是 READY 状态的正常维护手段。

```text
select bounded directory batch
→ provider list
→ fingerprint
→ compare baseline
→ clean / dirty
```

它不是 Full Scan。

Scheduler 只提供预算：

```text
verify_root(root, budget=20 dirs)
```

Kernel 自己决定优先目录。

---

# 24. Full Audit

Full Audit 用来验证事实，不直接覆盖事实。

```text
durable full scan
→ audit staging
→ complete gate
→ diff against canonical inventory
→ report
```

默认：

```text
REPORT ONLY
```

Repair 必须显式执行。

Audit 失败不能污染 Canonical Inventory。

---

# 25. Provider Capability

Kernel 根据 Provider capability 选择策略。

```text
supports_stable_id
supports_delta
supports_cursor
supports_webhook
supports_checksum
supports_fast_list
```

Capability 必须来自 Provider Adapter 的真实声明。

禁止宿主代码猜。

---

# 26. Scheduler 不再拥有索引策略

旧式：

```text
scheduler
→ decide full sync
→ call v2
→ rebuild search
```

新的：

```text
scheduler
→ kernel.run_cycle(root_id)
```

Kernel 根据 Root State 决定：

```text
bootstrap
resume
incremental
verification
audit
rebuild
```

Scheduler 只负责：

- 时间；
- 并发预算；
- cancellation；
- 进程生命周期。

---

# 27. Admin UI 不再读取拼接状态

Admin 只能读取：

```text
KernelStatus
RootStatus
RunStatus
```

状态必须由 Kernel Query API 给出。

UI 不得使用：

- task handle；
- scheduler mutex；
- system_settings 自拼状态；
- legacy sync 表；

推导“正在索引”。

---

# 28. Kernel Status

建议统一：

```text
KernelHealth
RootStateView
RunProgressView
```

RunProgress 至少：

```text
run_id
root_id
mode
status

directories_discovered
directories_done
directories_pending
directories_failed

entries_discovered

active_workers
recent_paths

started_at
updated_at

can_resume
can_cancel

last_error
```

目录总数动态发现时禁止显示虚假百分比。

---

# 29. Kernel 配置

Kernel Config 必须显式对象化：

```python
KernelConfig(
    max_directory_workers=8,
    global_provider_concurrency=16,
    resume_max_age=3600,
    removal_ratio_guard=...,
    verification_batch_size=20,
)
```

Kernel 不读取：

```text
os.environ
CloudSite settings singleton
FastAPI dependency
```

CloudSite 启动时构造 Config 后注入。

---

# 30. 日志与可观测性

Kernel 通过 EventSink / Logger Port 发出结构化事件。

例如：

```text
run_started
directory_failed
run_interrupted
run_resumed
complete_gate_failed
reconcile_started
reconcile_committed
removal_guard_triggered
identity_conflict
root_degraded
audit_diff_ready
```

CloudSite 可以把它写：

- operation_logs；
- stdout；
- metrics；
- tracing。

Kernel 不知道最终写哪里。

---

# 31. 错误模型

禁止核心路径大量抛裸 Exception。

定义稳定错误类型：

```text
ProviderUnavailable
ProviderAuthError
ProviderPermissionError
RootMissing
PaginationIncomplete
CheckpointConflict
SnapshotIncomplete
IdentityConflict
RemovalGuardTriggered
ReconcileConflict
StorageFailure
RunExpired
RunCancelled
```

每类错误明确：

- retryable；
- destructive-safe；
- root state transition；
- operator action。

---

# 32. 事务模型

Kernel 明确区分：

### Runtime State Transaction

用于：

- run；
- dir queue；
- staging；
- progress。

### Canonical Commit Transaction

用于：

- identity；
- inventory；
- change journal；
- root generation。

原则：

> 扫描进度可逐步提交，Canonical Inventory 必须原子提交。

---

# 33. SQLite 规则

第一阶段继续支持 SQLite，但要求：

- WAL；
- bounded writer；
- 短 checkpoint transaction；
- reconcile single writer；
- busy timeout；
- 明确 retry；
- 禁止多个 worker 同时持长期写事务；
- migration 幂等。

内核测试必须包含 lock / crash / retry。

---

# 34. 与 CloudSite 1.0.0 的关系

新主线建议：

```text
CloudSite v1.0.0
      +
Index V2 Kernel
      =
CloudSite new baseline
```

不是：

```text
CloudSite current 2.0
      -
bugs
```

1.0.0 保留：

- 用户系统；
- 管理后台；
- 浏览；
- 下载；
- 预览；
- 收藏；
- 分享；
- Docker 部署。

首先只替换：

```text
V1 indexing
→ Index V2 Kernel
```

其余 2.0 功能后续逐个重新评估。

---

# 35. 1.0 接入方式

第一阶段通过 Compatibility Projection：

```text
Index Kernel Canonical Inventory
            │
            ▼
  CloudSite v1 resources projection
            │
            ├── Browse
            ├── Download
            └── Search
```

这样不要求一开始重写 1.0 全部查询层。

等 Kernel 稳定后再逐步让 Browse 直接读 Kernel Query API。

---

# 36. 当前 2.0 V2 代码如何处理

当前 `modules/indexing` 不直接删除。

定义为：

```text
REFERENCE IMPLEMENTATION / DONOR
```

从中提取已经验证的算法：

- concurrent scanner；
- durable checkpoint；
- staging；
- complete gate；
- reconcile change types；
- removal suppression；
- identity matching；
- dirty scope；
- directory fingerprint；
- rolling verification；
- audit diff；
- fault injection tests。

禁止原样搬运：

- legacy_bridge；
- CloudSite DB session import；
- Search rebuild wiring；
- Admin status wiring；
- platform/tasks 强耦合；
- Resources/Identity/Providers 模块依赖；
- system_settings v2_sync_progress；
- legacy sync compatibility ownership。

原则：

> 搬算法，不搬耦合。

---

# 37. 代码迁移映射

当前：

```text
modules/indexing/domain/*
```

优先进入：

```text
index_kernel/domain/*
```

当前：

```text
application/reconcile.py
dirty_scope_merge.py
verification_batch_selector.py
audit_repair_decision.py
```

经去 CloudSite 依赖后进入：

```text
index_kernel/engine/*
```

当前：

```text
durable_scan_repository.py
dirty_scope_repository.py
root_state_repository.py
verification_state_repository.py
```

重新实现为：

```text
index_kernel/storage/sqlite/*
```

当前：

```text
legacy_bridge.py
tasks/sync.py
```

不进入 Kernel。

---

# 38. 开发阶段重新编号

## K0 — Kernel Contract

完成：

- domain types；
- ports；
- config；
- error model；
- command/query surface；
- dependency guard。

此阶段不接生产。

## K1 — Canonical Store

完成：

- kernel schema；
- root；
- inventory；
- identity；
- change journal；
- migration tests。

## K2 — Bootstrap Scanner

完成：

- bounded scanner；
- durable run；
- checkpoint；
- staging；
- resume。

## K3 — Safe Reconcile

完成：

- complete gate；
- stable identity；
- atomic reconcile；
- removal guard；
- change journal commit。

## K4 — 1.0 Compatibility Integration

完成：

- AList Provider Adapter；
- v1 inventory projection；
- Browse/Search/Download E2E。

达到这一阶段后，新主线必须已经“可用”。

## K5 — Root Lifecycle

完成：

- READY；
- RESUME_REQUIRED；
- DEGRADED；
- REBUILD_REQUIRED；
- run_cycle。

## K6 — Verification / Dirty Scope

完成：

- fingerprints；
- rolling verification；
- dirty targeted reconcile。

## K7 — Search Projection

完成：

- change journal consumer；
- replay；
- dirty recovery；
- rebuild fallback。

## K8 — Audit / Repair

完成：

- report-only audit；
- repair plan；
- targeted repair；
- rebuild decision。

## K9 — Native Provider Delta

只在真实 Provider 支持 cursor/delta 后推进。

---

# 39. 每个阶段的硬门禁

每一阶段必须通过：

1. Correctness；
2. Data Safety；
3. Crash Recovery；
4. Concurrency Safety；
5. Idempotency；
6. Multi-Root Isolation；
7. Multi-Connection Isolation；
8. Observability；
9. Rollback；
10. Dependency Boundary。

Kernel Boundary 不通过：

> CI 直接失败。

---

# 40. 必须新增 Architecture Tests

例如静态检查：

```text
index_kernel/domain
index_kernel/engine
index_kernel/runtime
```

禁止 import：

```text
cloudsite.modules
cloudsite.routers
cloudsite.main
fastapi
```

允许：

```text
index_kernel.*
stdlib
明确批准的基础库
```

任何跨边界 import 必须通过 Adapter。

---

# 41. Fault Injection 是 Kernel 正式测试

必须自动化模拟：

- list 前崩溃；
- list 后 checkpoint 前崩溃；
- entries 写入后 dir done 前崩溃；
- dir done 后崩溃；
- scan complete 后 reconcile 前崩溃；
- reconcile 中崩溃；
- commit 后 consumer 前崩溃；
- Provider 50% 时断开；
- permission 改变；
- root 临时消失；
- malformed page；
- SQLite lock；
- duplicate provider response。

不能只靠 CI “跑通”。

---

# 42. Golden Inventory

建立固定 Provider Fixture。

所有模式最终必须产生相同 Golden Inventory：

```text
serial bootstrap
concurrent bootstrap
crash + resume
full audit
dirty targeted repair
```

必须比较：

- resource IDs；
- folder IDs；
- paths；
- parents；
- metadata；
- generation；
- change sequence。

---

# 43. 内核级 Definition of Done

Index V2 Kernel 完成必须满足：

- Kernel 不依赖 CloudSite 业务模块；
- Canonical Inventory 只有一个事实源；
- Stable Identity 属于 Kernel；
- crash 后可 resume；
- partial scan 永不误删；
- reconcile 原子；
- READY 不频繁全量；
- Search/Catalog 故障不影响 Kernel；
- Provider 暂时故障不污染事实；
- 多 Root 不互相覆盖；
- 多 Connection 不互相覆盖；
- 所有变化都有 Change Journal；
- 所有运行状态可查询；
- 可从 v1.0.0 接入；
- Kernel 可以在无 FastAPI、无 Web、无 Search 的测试进程中完整运行。

最后一条是“内核级”的最直接验收：

> **如果离开 CloudSite Web/API 后 Index V2 就不能运行，它就还不是内核。**

---

# 44. 明确禁止

禁止重新出现：

- Kernel import CloudSite modules；
- CloudSite Scheduler 拼接 Index 算法；
- Search rebuild 写在同步函数尾部；
- system_settings 保存核心运行状态；
- Admin task handle 代表索引事实；
- V2 使用 Legacy sync 表；
- 扫描半成品直接覆盖 Production；
- path hash 作为最终 Identity；
- Provider error 当 empty；
- 每次同步 full scan；
- 每次变化 full search rebuild；
- 业务模块各自维护一份 Folder/Resource 真相；
- 为了“模块化”继续添加无实际必要的 facade/bridge/contract。

---

# 45. 当前仓库的处理策略

当前 main 不再作为新架构继续扩建。

建议分支：

```text
main
└── archive/current-2.0

design/index-v2-kernel
└── 本文档与 Kernel 设计

v1.0.0
└── rebuild/v1-index-kernel
    ├── K0
    ├── K1
    ├── K2
    ├── K3
    └── K4
```

当前 2.0 的 V2 代码继续作为 donor。

任何代码进入 `rebuild/v1-index-kernel` 前必须证明：

> 它是 Kernel 必需能力，而不是 2.0 架构债务。

---

# 46. 第一批实际工作

正式开发顺序：

```text
1. 冻结 current 2.0
2. 保留现有 V2 文档和测试
3. 从 v1.0.0 创建 rebuild/v1-index-kernel
4. 建 index_kernel 空骨架
5. 写 Ports / Domain / Error / Config
6. 建 Kernel SQLite schema
7. 从现有 V2 移植 scanner + durable scan
8. 移植 reconcile + identity + safety guards
9. 接 AList ProviderPort
10. 生成 Canonical Inventory
11. 做 v1 compatibility projection
12. 跑 Browse/Search/Download E2E
13. 通过 crash/fault/golden inventory
14. 才进入 lifecycle / incremental / verification
```

K0-K4 之前：

> 不开发新 UI，不开发 AI，不继续 Catalog 自动化，不做无关模块化整理。

---

# 47. 最终原则

CloudSite 的长期价值不应建立在大量业务模块的复杂组合上。

真正需要稳定的是：

```text
Provider
   ↓
INDEX KERNEL
   ↓
Canonical Resource Truth
   ↓
Everything Else
```

Index V2 必须像数据库存储引擎、文件系统索引器或搜索引擎核心一样被对待：

- 边界窄；
- 事实明确；
- 事务明确；
- 故障安全；
- 可恢复；
- 可测试；
- 可替换宿主；
- 不依赖 UI；
- 不依赖业务模块；
- 不依赖当前 CloudSite 2.0 的架构形态。

**CloudSite 可以重写，Index Kernel 的事实语义不能漂移。**
