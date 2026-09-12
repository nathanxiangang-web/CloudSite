# CloudSite 模块化开发文档（优化）

> 文档版本：`2.0-modular-draft`  
> 编制日期：`2026-09-10`  
> 源码审查基线：CloudSite `v1.0.0`，Git Tree `c46a1d94c10d29ba0168f6c5988bc5ce75cdc69c`  
> 目标版本：CloudSite 2.0  
> 适用对象：架构师、模块负责人、Codex / CodeArts / DeepSeek 等 AI 开发 Agent、测试与发布人员  
> 关联文档：`新架构开发文档.md`  
> 核心目标：把 CloudSite 从“已经拆了不少文件的单体项目”，升级为“可以按模块并行开发、按合同独立验收、由 AI 在新会话中快速恢复上下文的模块化单体”。

---

# 0. 执行结论

## 0.1 当前 1.0 是否足够模块化

结论：

> **CloudSite 1.0 已经完成了初步目录拆分，但还没有形成真正可以“一人负责一个模块、各自独立开发、最后安全组合”的模块边界。**

它不是完全混乱的单体项目。当前已经具备：

- 前台路由与后台路由分离；
- `routers/`、`services/`、`providers/`、`sync/`、`identity/`、`shares/`、`tasks/`、`infrastructure/` 等包；
- `main.py` 已从早期超级文件缩小为应用组装入口；
- `state.db` 与 `index.db` 有明确恢复边界；
- 后端、前端、Docker、备份和依赖审计已有 CI；
- Provider、稳定资源身份、同步器、分享系统已经开始独立封装。

这些说明 1.0 的工程基础是合格的。

但从“多人或多 AI Agent 并行开发”的角度看，当前仍有明显问题：

- 业务模块没有完整拥有自己的 API、业务逻辑、数据模型、仓储、测试和文档；
- 大量模块仍共享 `models.py`、`schemas.py`、`database.py`、`main.py` 和 `globals.css`；
- 路由层直接执行 SQL、组织业务流程、处理权限和序列化；
- `services/` 中部分文件只是 DTO 转换工具，并不是完整应用服务；
- 多个模块通过 `cloudsite.main` 获取 Session、函数或可被 monkeypatch 的符号；
- Provider 接口仍向外暴露 `dict[str, Any]` 和 `Any`；
- 同步、索引、身份、搜索之间边界交叉；
- 前端组件仍较平铺，样式集中在一个约 140 KB 的全局 CSS 文件中；
- 没有模块清单、模块负责人、依赖规则、架构测试和 AI 上下文包；
- 新会话只能重新搜索整个仓库，缺少稳定、精简、可验证的项目记忆。

因此，当前状态可以概括为：

```text
文件级拆分：已有
目录级拆分：已有
业务边界：部分存在
数据所有权：不足
依赖方向：未强制
独立验收：不足
AI 会话恢复：不足
多人并行开发：风险较高
```

建议的主观评分如下，仅用于判断优先级：

| 维度 | 当前评价 |
|---|---:|
| 目录结构 | 7/10 |
| 业务模块边界 | 4/10 |
| 数据所有权 | 3/10 |
| 依赖方向 | 4/10 |
| 独立测试能力 | 5/10 |
| 多 Agent 并行能力 | 3/10 |
| AI 上下文恢复能力 | 2/10 |
| 综合判断 | 约 4.5/10 |

1.0 足够支持一个主要开发者继续维护，但不适合代码继续快速膨胀后，依靠多个 AI 长期并行修改。

---

## 0.2 目标架构

CloudSite 2.0 不采用微服务，采用：

> **模块化单体（Modular Monolith）+ 垂直业务模块（Vertical Module）+ Ports & Adapters + Contract First。**

部署形态仍然可以保持简单：

```text
cloudsite-web
cloudsite-api
cloudsite-worker
postgres
```

其中：

- `api` 与 `worker` 使用同一个代码仓库和相同业务模块；
- API 进程负责 HTTP 请求；
- Worker 进程负责索引、扫描、任务和后台作业；
- PostgreSQL 作为 2.0 权威数据与任务数据库；
- 首期不强制引入 Redis；
- 所有模块仍可随同一个版本一起发布；
- 模块边界先在代码和数据层强制，未来确有需要时再拆服务。

核心原则：

```text
一个模块
= 自己的领域规则
+ 自己的应用服务
+ 自己的 API
+ 自己的数据表
+ 自己的仓储实现
+ 自己的测试
+ 自己的模块文档
+ 自己的负责人
```

---

## 0.3 对“每人负责一个模块，最后组合”的修正

方向是对的，但不能采用：

```text
所有人各自开发几周
→ 最后一天一次性合并
→ 再开始解决冲突
```

正确方式是：

```text
先冻结蓝图和合同
→ 为每个模块建立空壳与 Fake
→ 各模块独立开发
→ 每 1～2 天持续合并到 v2 集成分支
→ 功能未完成时由 Feature Flag 关闭
→ 持续运行合同测试和系统测试
→ 所有模块完成后只做启用和发布，不做第一次集成
```

因此应坚持：

> **独立开发可以，最后一次性集成不可以。**

真正的“最后组合”应该只剩：

- 打开功能开关；
- 运行数据迁移；
- 完整回归；
- 发布 RC；
- 灰度切换；
- 保留回滚入口。

---

# 1. CloudSite 1.0 源码模块化审查

## 1.1 当前后端结构优点

当前 `apps/api/cloudsite/` 已经有较明显的职责目录：

```text
cloudsite/
├── routers/
├── services/
├── providers/
├── sync/
├── identity/
├── shares/
├── tasks/
├── infrastructure/
├── main.py
├── models.py
├── schemas.py
├── database.py
├── indexer.py
├── search.py
├── auth.py
├── users.py
└── userdata.py
```

其中值得保留的方向：

1. `main.py` 主要负责 FastAPI 初始化和 Router 注册；
2. 前台路由与 `routers/admin/` 已经分开；
3. Provider 已经存在 Protocol、能力声明和 Registry；
4. `identity/` 已拆出指纹、迁移、Schema 和服务；
5. `shares/` 已拆出提取码、票据和服务；
6. `sync/` 已拆出 Governor、Planner、手动路径同步和 Rolling；
7. `tasks/` 已拆出 Scheduler；
8. `infrastructure/` 已拆出生命周期、中间件、安全和异常处理。

这说明无需把整个项目全部删除重写。2.0 应当保留有效设计，替换错误边界。

---

## 1.2 当前主要代码热点

### 1.2.1 `sync/rolling.py`

当前约 53 KB，是最明显的超级模块之一，同时承担：

- 周期创建；
- 窗口计划；
- 上游请求；
- 请求治理；
- 目录校验；
- 指纹计算；
- 资源和目录写入；
- 缺失确认；
- 移动与复制候选；
- 稳定身份协调；
- FTS 增量更新；
- 异常回滚；
- 熔断处理；
- 运行统计；
- 状态输出。

这不是一个模块，而是多个职责被压在一个文件中。

新的 2.0 索引架构不得继续写入这个文件。旧 Rolling 只保留在 1.x 维护线，2.0 新建独立 `indexing` 模块。

### 1.2.2 `indexer.py`

当前约 31 KB，同时包含：

- 路径工具；
- 旧全量扫描；
- Rate Limiter；
- 上游访问限制识别；
- 同步熔断；
- 资源变化判断；
- 身份解析；
- 数据库提交；
- 搜索重建；
- 日志记录。

它同时是工具库、领域服务、应用编排器和基础设施适配器，边界不清楚。

### 1.2.3 `models.py`

当前约 34 KB，包含：

- AList 连接；
- 站点配置；
- 用户与 Session；
- 收藏、历史、播放进度；
- 分享；
- 合集；
- 投稿；
- 通知；
- 下载限流；
- 稳定身份；
- 资源与目录；
- 同步 Run、Cycle、Item；
- Provider 状态。

所有模块修改数据库时都会触碰同一个文件，极易造成：

- Agent 修改冲突；
- 数据所有权不清；
- 模块无法单独加载测试；
- 一个模型变化影响大量无关模块；
- AI 需要读取整份文件才能理解局部功能。

### 1.2.4 `schemas.py`

当前约 8 KB，但已经集中定义：

- AList；
- Content Root；
- Site；
- Auth；
- User；
- Share；
- Collection；
- Resource；
- Folder；
- Search；
- Submission；
- Notification；
- Sync。

文件还会继续增长。更大的问题不是行数，而是任何模块都依赖同一个 Schema 集合，无法判断哪个 DTO 属于谁、哪些是内部模型、哪些是稳定公共合同。

### 1.2.5 `database.py`

当前同时承担：

- Engine 和 Session 工厂；
- SQLite PRAGMA；
- 文件完整性校验；
- 数据库身份判断；
- 恢复状态判断；
- 迁移前备份；
- 建表；
- 大量手工 `ALTER TABLE`；
- Schema 版本处理。

数据库连接、迁移、恢复和业务表补丁混在一起。随着模块增加，这个文件会成为所有模块共同修改的中心冲突点。

### 1.2.6 `main.py`

当前 `main.py` 已经不算大，但仍存在一种隐性耦合：

```text
其他模块通过 cloudsite.main 获取 Session 或函数
测试通过 monkeypatch cloudsite.main 上的 re-export 符号
main.py 为兼容这些调用继续导入并重新导出大量内部实现
```

这使 `main.py` 逐渐变成 Service Locator。

2.0 应让测试直接注入 Fake Port，不再依赖 `main.py` 作为全局中转站。

### 1.2.7 路由层过重

以 `routers/resources.py` 为例，路由中直接完成：

- SQLAlchemy 查询；
- 双数据库 Session 管理；
- 发布范围判断；
- 分页；
- 排序；
- 关联资源查询；
- 前后资源查询；
- Preview 判断；
- Office 缓存；
- DTO 拼装。

这意味着“资源模块”并没有一个完整的应用服务，API 层只是另一个业务层。

正确边界应该是：

```text
Router
→ 验证 HTTP 输入和身份
→ 调用 Use Case
→ 返回合同 DTO
```

Router 不应知道 SQLAlchemy 表和查询细节。

### 1.2.8 Auth 边界混合

当前 `auth.py` 同时包含：

- Router；
- 用户名规则；
- 密码规则；
- 密码哈希；
- CSRF Origin；
- Session 验证；
- 用户注册；
- 登录；
- 改密；
- ORM 查询；
- 操作日志；
- DTO 序列化。

`users.py` 又直接引用 `auth.py` 的哈希、校验和 DTO 函数。

这属于“按文件拆开了，但内部仍互相调用实现细节”。

### 1.2.9 `userdata.py`

收藏、浏览历史、播放进度三个子领域集中在一个约 15 KB 的文件中，并同时访问：

- 用户数据库；
- 资源索引数据库；
- Publication Scope；
- 资源序列化；
- 清理策略；
- 播放完成判定。

可以归入同一个 `user_library` 模块，但必须再拆成独立 Use Case 和 Repository。

### 1.2.10 Provider 抽象仍未闭合

当前已有 `StorageProvider` Protocol，是正确方向，但接口仍返回：

```python
list[dict[str, Any]]
Any
dict[str, Any]
```

`GenericAListProvider` 仍直接返回 `AListDownloadEntry`。

这会导致：

```text
上游 AList 字段
→ 泄露到 Indexing
→ 泄露到 Delivery
→ 泄露到 Preview
→ 第二个 Provider 接入时全链路修改
```

2.0 必须由 `storage` 模块定义 CloudSite 自己的稳定 DTO，其他模块不允许看到 AList 原始响应。

---

## 1.3 当前前端结构问题

现有前端已经使用 Next.js App Router，并具有：

```text
src/
├── app/
├── components/
├── lib/
└── proxy.ts
```

但业务组件大多平铺在 `components/`，例如：

- HomeContent；
- ResourceCard；
- DownloadButton；
- ShareDialog；
- NotificationBell；
- OfficePreview；
- AdminShell；
- PublicShell。

`lib/api.ts` 同时包含：

- 多个领域 DTO；
- HTTP Client；
- Auth Fuse；
- 错误类型；
- 格式化工具。

`app/globals.css` 约 140 KB，已经成为前端最大的共享修改热点。

当前前端属于：

> **页面已拆分，业务 Feature 未真正拆分。**

后续每个 Agent 修改 UI 时，很容易共同修改：

```text
components/
lib/api.ts
globals.css
admin/page.tsx
```

因此前端必须改为 Feature 模块结构。

---

## 1.4 当前文档和 AI 上下文问题

1.0 已经有：

- `docs/architecture.md`
- `docs/contracts.md`
- 安装、升级、备份、恢复和限制文档。

这些文档适合解释整个系统和交付方式，但仍缺少：

- 根级 `AGENTS.md`；
- 模块清单；
- 每个模块的 `MODULE.md`；
- 模块负责人；
- 允许依赖和禁止依赖；
- 数据表所有权；
- 内部 Port 合同；
- ADR 决策记录；
- 当前项目状态快照；
- AI 任务单；
- AI 会话交接；
- 自动生成的模块上下文包。

因此，新会话只能“重新理解整个项目”，而不是“装载目标模块”。

---

# 2. 为什么代码越大，AI 开发越困难

AI 开发难度增加，不只是因为代码行数增加，主要来自以下六种复杂度。

## 2.1 上下文选择困难

当项目中存在多个同名概念时，AI 不知道应该读取：

```text
routers/resources.py
services/resources.py
models.py
schemas.py
search.py
shares/service.py
frontend lib/api.ts
```

为了避免漏读，AI 会不断扩大搜索范围，最终把大量无关内容装入上下文。

---

## 2.2 依赖关系隐藏

当前许多依赖通过：

- 延迟 import；
- `main.py` re-export；
- 全局 Session；
- ORM 模型；
- 公共工具函数；
- monkeypatch；

连接起来。

AI 很难在有限上下文中确认“改这个函数会影响哪些模块”。

---

## 2.3 共享文件过多

多人或多 Agent 最害怕的不是文件多，而是所有任务都要修改同一批文件。

当前热点包括：

```text
models.py
schemas.py
database.py
main.py
globals.css
lib/api.ts
rolling.py
```

即使每个人负责不同功能，最后仍会在这些文件冲突。

---

## 2.4 任务边界不明确

“实现新索引系统”是一个大目标，不是可执行任务。

AI 更适合：

```text
只在 indexing 模块中实现 CategoryInventorySnapshot 校验；
输入合同已经冻结；
不得修改 catalog 和 storage 实现；
通过指定 8 个测试后完成。
```

模块化的本质，是把任务从“理解整个系统”缩小到“理解一个稳定边界”。

---

## 2.5 决策只存在于聊天记录

聊天上下文会压缩、截断或换会话。

如果关键决定只在聊天里，例如：

```text
一个资源一个文件夹
分类扫描不进入全部资源目录
PostgreSQL 首期不使用 Redis
稳定 ID 来自 Manifest UUID
```

新会话就会重新争论，甚至走回旧方案。

正确原则：

> **聊天是临时缓存，Git 仓库才是项目长期记忆。**

---

## 2.6 最后一次性集成造成认知爆炸

多个 Agent 独立修改很久后再合并，会同时出现：

- 接口不一致；
- DTO 字段不一致；
- 数据表冲突；
- 路由重复；
- Feature Flag 不一致；
- 前端与后端版本不一致；
- 多份“各自正确”的实现。

此时任何一个 AI 都必须重新理解所有模块，模块化收益全部消失。

---

# 3. CloudSite 2.0 模块化总原则

## 3.1 采用模块化单体，不采用微服务

当前阶段不建议：

- 每个模块单独仓库；
- 每个模块独立部署；
- 每个模块单独数据库实例；
- 引入 Kubernetes；
- 引入大量 RPC；
- 通过网络调用所有内部功能。

原因：

- CloudSite 当前团队规模不需要微服务；
- 运维复杂度会显著增加；
- 分布式事务和可观测性成本更高；
- AI 会同时面对代码复杂度和部署复杂度；
- 模块边界可以先在单仓库、单数据库和单发布物中强制。

模块化单体可以获得：

- 清晰边界；
- 独立所有权；
- 独立测试；
- 并行开发；
- 简单部署；
- 必要时可抽离。

---

## 3.2 按业务模块纵向拆分，不再只按技术层横向拆分

不推荐继续扩大：

```text
routers/
services/
models/
repositories/
schemas/
```

这种全局横向目录。

因为 Catalog、IAM、Sharing、Indexing 的文件仍混在相同目录中，所有人都会修改它们。

目标结构是：

```text
modules/
├── iam/
├── catalog/
├── storage/
├── indexing/
├── search/
├── delivery/
├── sharing/
├── curation/
├── user_library/
├── contributions/
├── communications/
├── site/
└── operations/
```

每个模块内部再分：

```text
api/
application/
domain/
infrastructure/
public/
tests/
```

---

## 3.3 一个模块只有一个公开入口

模块对外只允许暴露：

```text
modules/<name>/public/
modules/<name>/module.py
```

其他模块禁止导入：

```text
modules/<name>/domain/*
modules/<name>/application/*
modules/<name>/infrastructure/*
modules/<name>/api/*
```

例如：

```python
# 允许
from cloudsite.modules.catalog.public.queries import CatalogQueryPort

# 禁止
from cloudsite.modules.catalog.infrastructure.models import ResourceRow
from cloudsite.modules.catalog.application.resource_service import ResourceService
```

---

## 3.4 模块拥有自己的数据

每张表必须只有一个业务模块拥有。

模块所有权意味着：

- 只有该模块可以写入；
- 只有该模块定义 ORM Model；
- 只有该模块维护迁移；
- 其他模块不得直接查询该表；
- 其他模块通过 Query Port、Command Port 或事件读取数据。

---

## 3.5 模块间通过强类型合同通信

禁止跨模块传播：

```text
dict[str, Any]
SQLAlchemy ORM Row
Request
Session
Provider 原始 JSON
AListDownloadEntry
数据库连接
内部异常
```

模块边界只允许：

- 不可变 DTO；
- Protocol / Port；
- Command；
- Query；
- Domain Event；
- 统一 Error Code。

---

## 3.6 显式注册，不使用隐藏魔法

模块注册由 Composition Root 明确完成。

不建议通过：

- 扫描文件夹自动加载；
- import side effect；
- 动态反射猜测依赖；
- 全局单例自动注册。

对 AI 开发而言，显式结构更容易理解和验证。

---

## 3.7 先冻结合同，再并行实现

并行开发的前置条件不是“建好分支”，而是：

- API 合同；
- 内部 Port；
- 数据归属；
- 事件结构；
- 错误码；
- 验收测试；

已经冻结。

否则模块负责人会各自发明接口，最后无法组合。

---

## 3.8 任何积压不得推动架构越界

不能因为赶进度而：

- 直接跨模块查表；
- 临时把函数放进 `shared/`；
- 重新把 Schema 放回全局；
- 在 Router 中写完整业务；
- 使用 `Any` 跳过类型；
- 让 Agent 顺手修改其他模块。

临时越界通常会永久留下。

---

# 4. 目标模块地图

## 4.1 核心业务模块

| 模块 | 主要职责 | 当前 1.0 来源 |
|---|---|---|
| `iam` | 前台用户、管理员、Session、密码、权限、CSRF | `auth.py`、`users.py`、`sessions.py`、`admin_auth.py` |
| `site` | 站点信息、注册开关、展示配置、内容根展示配置 | `site.py`、`site_assets.py`、SiteSettings 相关 |
| `storage` | 存储连接、Provider、AList/OpenList Adapter、能力协商 | `alist.py`、`providers/*`、后台 AList 路由 |
| `catalog` | 分类、资源、资源文件、Manifest、稳定 Resource ID、资源状态 | `Folder`、`Resource`、`identity/*` 的业务部分 |
| `indexing` | 分类库存快照、资源补全、任务队列、调度、熔断、扫描状态 | `indexer.py`、`sync/*`，并按新索引架构重写 |
| `search` | PostgreSQL 搜索投影、索引更新、搜索 API | `search.py`、搜索路由 |
| `delivery` | 下载、预览、Office/PDF/文本、下载限流与诊断 | `download.py`、`preview.py`、`office.py`、相关路由 |
| `sharing` | 分享、提取码、Ticket、分享权限和生命周期 | `shares/*`、分享路由和后台分享 |
| `curation` | 合集、首页精选、排序、封面和运营推荐 | Collections、Featured Collections |
| `user_library` | 收藏、历史、播放进度、个人资源状态 | `userdata.py` |
| `contributions` | 用户投稿、审核、发布关联 | Submissions |
| `communications` | 通知、公告、用户通知状态 | Notifications |
| `operations` | 运行状态、诊断、审计日志、任务控制、健康检查 | Admin Overview、Diagnostics、System、OperationLog |

## 4.2 组合模块

增加轻量 `portal` 模块，只负责组合读模型：

```text
/api/v2/home
/api/v2/navigation
/api/v2/bootstrap
```

它可以读取：

- Site Query；
- Catalog Query；
- Search Query；
- Curation Query；
- 当前用户摘要。

它不拥有核心业务表，不允许在内部重新实现其他模块规则。

---

## 4.3 模块负责人规则

一个模块只能有一个当前责任人：

```text
Module Owner
```

但不意味着只有该人永远可以写代码。

责任人负责：

- 模块合同；
- 模块数据；
- 模块文档；
- 模块 PR 审核；
- 模块质量；
- 模块兼容性；
- 跨模块变更确认。

AI 场景中，可以把责任人映射为：

```text
catalog-owner-agent
indexing-owner-agent
storage-owner-agent
iam-owner-agent
release-owner-agent
```

同一 Agent 可以暂时负责多个模块，但同一模块不能同时存在两个未经协调的决策者。

---

# 5. 模块依赖图

推荐依赖关系：

```text
                           ┌──────────────┐
                           │ shared_kernel│
                           └──────┬───────┘
          ┌───────────────┬───────┼───────────────┬──────────────┐
          ▼               ▼       ▼               ▼              ▼
        iam             site    storage          catalog       operations
                                  │                 │
                                  │                 ├────────► search
                                  │                 ├────────► curation
                                  │                 ├────────► user_library
                                  │                 ├────────► contributions
                                  │                 └────────► delivery
                                  │                                   │
                                  └────────► indexing ───────► catalog│
                                               │                      │
                                               └──── event ─────► search
                                                                      │
                       iam + catalog + delivery ───────────────► sharing
                       iam + events ──────────────────────────► communications

              site + catalog + search + curation + iam ──────► portal
```

解释：

- `storage` 不知道 Catalog 是什么；
- `catalog` 不知道 AList 是什么；
- `indexing` 通过 Storage Port 读取上游，再通过 Catalog Ingest Port 写入资源；
- `search` 维护自己的投影，不直接读取 Indexing 内部表；
- `delivery` 使用 Catalog 查询资源位置，再使用 Storage 获取下载入口；
- `sharing` 不直接拼接下载 URL，调用 Delivery Port；
- `portal` 是允许组合多个只读合同的边缘模块；
- `operations` 订阅状态和事件，不反向控制业务实现。

---

## 5.1 严禁形成的循环依赖

禁止：

```text
catalog ↔ indexing
storage ↔ delivery
sharing ↔ delivery
iam ↔ user_library
portal ↔ catalog
```

解决方法：

- Command/Query Port；
- Domain Event；
- Application Orchestrator；
- Read Projection；
- 把真正共同的不可变值对象放入极小的 `shared_kernel`。

不得通过把所有内容放进 `shared/` 来“解决”循环。

---

# 6. 后端目标目录结构

```text
apps/api/cloudsite/
├── bootstrap/
│   ├── app.py
│   ├── container.py
│   ├── module_registry.py
│   ├── lifecycle.py
│   └── settings.py
│
├── shared_kernel/
│   ├── ids.py
│   ├── clock.py
│   ├── pagination.py
│   ├── errors.py
│   ├── result.py
│   └── events.py
│
├── platform/
│   ├── db/
│   │   ├── engine.py
│   │   ├── sessions.py
│   │   ├── health.py
│   │   ├── recovery.py
│   │   ├── migration_runner.py
│   │   └── outbox.py
│   ├── http/
│   │   ├── middleware.py
│   │   ├── request_context.py
│   │   └── exception_handlers.py
│   ├── jobs/
│   │   ├── scheduler.py
│   │   └── worker_runtime.py
│   ├── observability/
│   │   ├── logging.py
│   │   ├── metrics.py
│   │   └── tracing.py
│   └── security/
│       ├── crypto.py
│       └── secrets.py
│
├── modules/
│   ├── iam/
│   ├── site/
│   ├── storage/
│   ├── catalog/
│   ├── indexing/
│   ├── search/
│   ├── delivery/
│   ├── sharing/
│   ├── curation/
│   ├── user_library/
│   ├── contributions/
│   ├── communications/
│   ├── operations/
│   └── portal/
│
└── main.py
```

最终 `main.py` 只保留：

```python
from cloudsite.bootstrap.app import create_app

app = create_app()
```

---

## 6.1 单个模块标准结构

以 `catalog` 为例：

```text
modules/catalog/
├── MODULE.md
├── module.yaml
├── module.py
│
├── public/
│   ├── commands.py
│   ├── queries.py
│   ├── events.py
│   ├── ports.py
│   ├── dto.py
│   └── errors.py
│
├── domain/
│   ├── entities.py
│   ├── value_objects.py
│   ├── policies.py
│   ├── services.py
│   └── exceptions.py
│
├── application/
│   ├── create_resource.py
│   ├── apply_inventory_snapshot.py
│   ├── get_resource.py
│   ├── list_category.py
│   └── handlers.py
│
├── infrastructure/
│   ├── models.py
│   ├── repositories.py
│   ├── query_service.py
│   ├── event_store.py
│   └── migrations/
│       ├── catalog_0001_initial.py
│       └── catalog_0002_resource_files.py
│
├── api/
│   ├── router.py
│   ├── admin_router.py
│   ├── request_models.py
│   ├── response_models.py
│   └── dependencies.py
│
└── tests/
    ├── unit/
    ├── contract/
    ├── integration/
    └── fixtures/
```

---

## 6.2 各层允许依赖

```text
domain
└── 只能依赖 Python 标准库和 shared_kernel 的稳定值对象

application
├── 可以依赖 domain
├── 可以依赖本模块 public
└── 可以依赖其他模块的 public contracts

infrastructure
├── 可以依赖 application/domain
├── 可以依赖 platform
└── 实现 Repository 和外部 Adapter

api
├── 可以依赖 application
├── 可以依赖 public DTO
└── 不得直接依赖 infrastructure models

module.py
└── 只负责把接口与实现组装起来
```

---

# 7. 模块注册与依赖注入

## 7.1 模块定义

建议使用简单、显式的模块定义：

```python
from dataclasses import dataclass
from collections.abc import Callable, Awaitable
from fastapi import APIRouter

@dataclass(frozen=True)
class ModuleDefinition:
    name: str
    depends_on: tuple[str, ...]
    build_router: Callable[["AppContainer"], APIRouter] | None = None
    startup_hooks: tuple[Callable[["AppContainer"], Awaitable[None]], ...] = ()
    shutdown_hooks: tuple[Callable[["AppContainer"], Awaitable[None]], ...] = ()
```

每个模块提供：

```python
# modules/catalog/module.py
module = ModuleDefinition(
    name="catalog",
    depends_on=(),
    build_router=build_catalog_router,
    startup_hooks=(verify_catalog_schema,),
)
```

Composition Root 显式注册：

```python
MODULES = (
    iam.module,
    site.module,
    storage.module,
    catalog.module,
    indexing.module,
    search.module,
    delivery.module,
    sharing.module,
    curation.module,
    user_library.module,
    contributions.module,
    communications.module,
    operations.module,
    portal.module,
)
```

启动时：

1. 校验模块名唯一；
2. 校验依赖存在；
3. 拓扑排序；
4. 组装 Port；
5. 注册 Router；
6. 执行 Startup Hook；
7. 输出模块健康状态。

---

## 7.2 AppContainer

不再通过 `cloudsite.main` 获取 Session 或全局函数。

```python
@dataclass
class AppContainer:
    db: DatabaseRuntime
    event_bus: EventBus
    clock: Clock
    settings: Settings
    ports: PortRegistry
```

模块在自己的 `module.py` 中注册实现：

```python
container.ports.bind(
    CatalogQueryPort,
    SqlAlchemyCatalogQueryService(session_factory=container.db.session_factory),
)
```

测试时替换为：

```python
container.ports.bind(CatalogQueryPort, FakeCatalogQuery())
```

这样测试无需 monkeypatch `main.py`。

---

# 8. 强类型模块合同

## 8.1 Storage 合同

2.0 禁止把 AList 原始响应传出 Storage 模块。

```python
@dataclass(frozen=True)
class StorageObject:
    object_id: str | None
    name: str
    path: str
    is_directory: bool
    size: int
    modified_at: datetime | None
    mime_type: str | None
    etag: str | None

@dataclass(frozen=True)
class StoragePage:
    items: tuple[StorageObject, ...]
    next_cursor: str | None
    complete: bool
    generation: str | None

class StorageInventoryPort(Protocol):
    async def list_children(
        self,
        source_id: SourceId,
        path: StoragePath,
        cursor: str | None = None,
        refresh: bool = False,
    ) -> StoragePage: ...
```

下载合同：

```python
@dataclass(frozen=True)
class DownloadEntry:
    url: str
    expires_at: datetime | None
    supports_range: bool | None
    headers: Mapping[str, str]

class StorageDeliveryPort(Protocol):
    async def resolve_download(
        self,
        source_id: SourceId,
        object_path: StoragePath,
    ) -> DownloadEntry: ...
```

任何 AList Token、字段和错误只能存在于：

```text
modules/storage/infrastructure/providers/alist/
```

---

## 8.2 Catalog 合同

```python
@dataclass(frozen=True)
class ResourceSummary:
    id: ResourceId
    title: str
    category_id: CategoryId
    status: ResourceStatus
    cover: str | None
    updated_at: datetime

class CatalogQueryPort(Protocol):
    async def get_resource(self, resource_id: ResourceId) -> ResourceDetail | None: ...
    async def list_category(self, query: CategoryQuery) -> Page[ResourceSummary]: ...

class CatalogIngestPort(Protocol):
    async def apply_category_snapshot(
        self,
        snapshot: CategoryInventorySnapshot,
    ) -> SnapshotApplyResult: ...

    async def apply_resource_manifest(
        self,
        manifest: ResourceManifest,
    ) -> ResourceHydrationResult: ...
```

Catalog 拥有资源最终状态，Indexing 不能直接写 Catalog 表。

---

## 8.3 Indexing 合同

```python
class IndexingCommandPort(Protocol):
    async def enqueue_category_scan(self, command: ScanCategory) -> JobId: ...
    async def enqueue_resource_hydration(self, command: HydrateResource) -> JobId: ...
    async def enqueue_reconciliation(self, command: ReconcileSource) -> JobId: ...

class IndexingQueryPort(Protocol):
    async def get_job(self, job_id: JobId) -> JobStatus: ...
    async def get_source_status(self, source_id: SourceId) -> SourceSyncStatus: ...
```

新的 20,000 资源索引架构全部在 `indexing` 内实现：

```text
分类库存快照
资源骨架
Manifest 补全
任务队列
Provider 请求预算
熔断
两份完整快照缺失确认
```

不得继续塞进 `rolling.py`。

---

## 8.4 Event 合同

事件必须不可变、可版本化。

```python
@dataclass(frozen=True)
class ResourceUpsertedV1:
    event_id: UUID
    occurred_at: datetime
    resource_id: ResourceId
    revision: int
    changed_fields: tuple[str, ...]
```

建议事件：

```text
catalog.resource_upserted.v1
catalog.resource_missing.v1
catalog.category_changed.v1
indexing.job_failed.v1
storage.source_circuit_opened.v1
delivery.download_completed.v1
iam.user_disabled.v1
contributions.submission_published.v1
```

Search、Operations、Communications 通过事件更新投影或通知，禁止直接侵入源模块。

---

# 9. 数据所有权和 PostgreSQL 设计

## 9.1 一个 PostgreSQL 实例，逻辑 Schema 分模块

2.0 推荐：

```text
PostgreSQL Database: cloudsite

Schemas:
├── iam
├── site
├── storage
├── catalog
├── indexing
├── search
├── delivery
├── sharing
├── curation
├── user_library
├── contributions
├── communications
├── operations
└── platform
```

部署仍是一套 PostgreSQL，不等于微服务。

优点：

- 表归属清晰；
- 表名不会无限冲突；
- 可以对跨 Schema SQL 做审计；
- 将来拆服务时边界清楚；
- AI 只需读取目标模块模型；
- Migration 可以按模块组织。

---

## 9.2 建议表归属

| 模块 | 主要拥有表 |
|---|---|
| `iam` | users、user_sessions、admin_sessions、login_attempts |
| `site` | site_settings、feature_flags、navigation_settings |
| `storage` | storage_connections、storage_sources、provider_capabilities、provider_credentials |
| `catalog` | categories、resources、resource_files、resource_manifests、resource_identities、resource_revisions |
| `indexing` | sync_jobs、inventory_snapshots、inventory_snapshot_items、resource_hydration_state、provider_rate_state、sync_runs |
| `search` | resource_search_documents、search_terms、search_zero_results |
| `delivery` | download_events、download_rate_limits、download_diagnostics、preview_cache_entries |
| `sharing` | shares、share_codes、share_tickets、share_access_attempts |
| `curation` | collections、collection_items、featured_slots |
| `user_library` | favorites、resource_history、playback_progress |
| `contributions` | submissions、submission_reviews |
| `communications` | notifications、notification_receipts |
| `operations` | operation_logs、health_events、admin_actions |
| `platform` | outbox_events、schema_migrations、job_leases |

---

## 9.3 跨模块数据访问规则

禁止：

```sql
SELECT * FROM catalog.resources
JOIN user_library.favorites ...
```

由任意业务模块直接跨 Schema 执行。

允许的方式：

1. 调用另一个模块的 Query Port；
2. 使用由事件构建的本模块 Read Projection；
3. 在 `portal` 组合层调用多个只读 Query；
4. 极少数必须强事务的场景，由架构师批准 Application Orchestrator；
5. 数据分析只读账户可以跨 Schema，但不得成为在线业务依赖。

---

## 9.4 迁移所有权

每个模块维护自己的 Migration：

```text
modules/catalog/infrastructure/migrations/catalog_0001_initial.py
modules/indexing/infrastructure/migrations/indexing_0001_jobs.py
```

但执行器必须统一：

```text
platform/db/migration_runner.py
```

统一执行器负责：

- 全局顺序；
- 锁；
- 失败回滚；
- 版本记录；
- 升级前检查；
- 备份要求；
- Downgrade 能力声明。

Migration ID 必须包含模块前缀，禁止所有人同时修改一个巨大迁移列表。

---

## 9.5 跨模块一致性

首期使用：

```text
本地事务 + Transactional Outbox + 幂等消费者
```

例如：

```text
Catalog 更新 Resource
→ 同一事务写入 platform.outbox_events
→ Worker 分发 ResourceUpsertedV1
→ Search 幂等更新搜索文档
```

不要求在一次数据库事务里同时修改 Catalog、Search、Operations、Notifications。

---

# 10. 前端模块化结构

## 10.1 目标结构

```text
apps/web/src/
├── app/
│   ├── page.tsx
│   ├── resource/[id]/page.tsx
│   ├── search/page.tsx
│   └── admin/...
│
├── features/
│   ├── iam/
│   ├── catalog/
│   ├── search/
│   ├── delivery/
│   ├── sharing/
│   ├── curation/
│   ├── user-library/
│   ├── contributions/
│   ├── communications/
│   ├── site/
│   └── operations/
│
├── shared/
│   ├── api/
│   │   ├── http-client.ts
│   │   ├── errors.ts
│   │   └── generated/
│   ├── ui/
│   ├── auth/
│   ├── hooks/
│   ├── lib/
│   └── styles/
│       ├── tokens.css
│       ├── reset.css
│       ├── theme.css
│       └── layout.css
│
└── proxy.ts
```

App Router 页面只负责装配：

```tsx
import { CatalogPage } from "@/features/catalog/pages/CatalogPage";

export default function Page() {
  return <CatalogPage />;
}
```

页面文件不得重新实现业务请求和状态机。

---

## 10.2 单个前端 Feature

```text
features/catalog/
├── MODULE.md
├── public.ts
├── api/
│   ├── client.ts
│   ├── queries.ts
│   └── mutations.ts
├── model/
│   ├── types.ts
│   ├── schema.ts
│   └── state.ts
├── components/
├── pages/
├── hooks/
├── styles/
└── tests/
```

其他 Feature 只能从：

```text
features/catalog/public.ts
```

导入公开组件或类型，禁止深层导入内部文件。

---

## 10.3 API 类型自动生成

当前 `lib/api.ts` 手工维护多个后端 DTO，后续非常容易与 FastAPI Schema 漂移。

2.0 应通过 OpenAPI 生成：

```text
src/shared/api/generated/
```

生成目录：

- 只读；
- 不允许手工修改；
- CI 检查是否与后端 OpenAPI 一致；
- Feature 只包装自己需要的接口。

`http-client.ts` 只负责：

- Cookie；
- 通用错误；
- Trace ID；
- Auth Fuse；
- 超时；
- 请求取消。

它不保存所有领域 DTO。

---

## 10.4 CSS 拆分

`globals.css` 最终只保留：

```text
Reset
Design Tokens
Theme Variables
基础字体
极少量全局布局
```

目标：

- 全局 CSS 软限制 15 KB；
- Feature 样式归入自己的 CSS Module 或 Feature 样式目录；
- 禁止新增业务页面样式到 `globals.css`；
- 共享组件样式由 `shared/ui` 所有；
- 修改 Design Token 必须由前端架构负责人审核。

---

# 11. 模块清单 `module.yaml`

每个模块必须有机器可读清单：

```yaml
name: catalog
version: 2.0.0
owner: catalog-owner
status: active

depends_on:
  - shared_kernel

public_python:
  - cloudsite.modules.catalog.public.commands
  - cloudsite.modules.catalog.public.queries
  - cloudsite.modules.catalog.public.events
  - cloudsite.modules.catalog.public.dto

public_http:
  - GET /api/v2/resources
  - GET /api/v2/resources/{resource_id}
  - GET /api/v2/categories/{category_id}

owned_schemas:
  - catalog

owned_tables:
  - catalog.categories
  - catalog.resources
  - catalog.resource_files
  - catalog.resource_manifests
  - catalog.resource_identities

publishes:
  - catalog.resource_upserted.v1
  - catalog.resource_missing.v1

consumes:
  - indexing.category_snapshot_completed.v1

feature_flags:
  - catalog_v2_reads
  - catalog_v2_writes

test_commands:
  - pytest cloudsite/modules/catalog/tests/unit
  - pytest cloudsite/modules/catalog/tests/contract
  - pytest cloudsite/modules/catalog/tests/integration
```

CI 根据 `module.yaml` 自动生成：

```text
docs/generated/module-map.md
docs/generated/dependency-graph.mmd
CODEOWNERS 建议检查
受影响模块测试矩阵
```

---

# 12. `MODULE.md`：每个 AI 新会话的核心上下文

每个模块必须维护一份不超过约 300 行的 `MODULE.md`。

模板：

```markdown
# Catalog Module

## 1. 使命
把分类、资源、资源文件和稳定资源身份作为 CloudSite 的权威内容模型。

## 2. 负责
- Category
- Resource
- ResourceFile
- ResourceManifest
- Stable Resource ID
- Resource lifecycle

## 3. 不负责
- 调用 AList
- 扫描调度
- 搜索排序
- 下载 URL
- 用户收藏

## 4. 公共合同
- CatalogQueryPort
- CatalogIngestPort
- ResourceUpsertedV1

## 5. 拥有数据
- catalog.categories
- catalog.resources
- ...

## 6. 依赖
- shared_kernel

## 7. 关键不变量
- 一个资源文件夹对应一个 Resource
- Manifest UUID 是最高优先级身份
- Indexing 只能通过 CatalogIngestPort 写入
- Resource 删除必须经过完整快照确认

## 8. 错误码
- CATALOG_RESOURCE_NOT_FOUND
- CATALOG_MANIFEST_INVALID

## 9. 测试命令
...

## 10. 当前状态
- 已完成
- 正在迁移
- 已知债务

## 11. 关联 ADR
- ADR-0007 Resource Identity
- ADR-0012 Category Inventory Snapshot
```

`MODULE.md` 不记录逐行代码细节，只记录：

- 边界；
- 不变量；
- 合同；
- 当前状态；
- 风险；
- 如何测试。

---

# 13. 项目长期记忆体系

## 13.1 必须建立的文档

```text
AGENTS.md
docs/
├── project/
│   ├── PROJECT_STATE.md
│   ├── ROADMAP.md
│   └── RELEASE_POLICY.md
├── architecture/
│   ├── SYSTEM_MAP.md
│   ├── DEPENDENCY_RULES.md
│   ├── DATA_OWNERSHIP.md
│   ├── RUNTIME_TOPOLOGY.md
│   └── adr/
│       ├── ADR-0001-modular-monolith.md
│       ├── ADR-0002-postgresql-module-schemas.md
│       └── ...
├── contracts/
│   ├── http/
│   ├── internal/
│   └── events/
├── generated/
│   ├── module-map.md
│   └── dependency-graph.mmd
└── modules/
    └── README.md
```

模块自己的文档放在代码旁：

```text
modules/<name>/MODULE.md
modules/<name>/module.yaml
```

---

## 13.2 信息权威顺序

出现冲突时，按以下优先级处理：

1. 已接受 ADR 和已发布 Contract；
2. `main` / `v2/integration` 最新代码及自动化测试；
3. `MODULE.md`；
4. `PROJECT_STATE.md`；
5. 当前任务单；
6. Handoff；
7. 聊天记录。

聊天中的决定，如果需要长期生效，必须转成：

- ADR；
- Contract；
- Module invariant；
- Task acceptance criterion。

否则不视为已正式决定。

---

## 13.3 根级 `AGENTS.md`

`AGENTS.md` 控制在约 150～250 行，必须包含：

- 项目定位；
- 目标架构；
- 模块列表；
- 依赖规则；
- 数据库规则；
- 测试规则；
- Git 规则；
- 安全规则；
- 禁止事项；
- AI 工作流程；
- 发布门槛。

禁止把所有业务细节都塞进 `AGENTS.md`。它是入口索引，不是百科全书。

---

## 13.4 `PROJECT_STATE.md`

由架构师在模块 PR 合并后更新，内容包括：

```text
当前发布版本
当前架构版本
正在启用的 Feature Flag
已迁移模块
Legacy 模块
活动 ADR
当前阻塞
最近一次完整回归
数据库迁移版本
下一里程碑
```

它不记录聊天过程和临时猜测。

---

# 14. AI 上下文窗口解决方案

## 14.1 新会话不得重新读取整个项目

每个新会话固定只先读取：

```text
1. AGENTS.md
2. docs/architecture/SYSTEM_MAP.md
3. 目标模块 MODULE.md
4. 当前 Task 文件
5. Task 引用的 Contract / ADR
6. 目标模块最近提交和测试
```

只有发现明确跨模块依赖时，才读取依赖模块的 `public/` 和 `MODULE.md`。

---

## 14.2 Context Pack

新增工具：

```text
scripts/dev/context_pack.py
```

调用：

```bash
python scripts/dev/context_pack.py \
  --module indexing \
  --task CS-INDEX-021 \
  --output .ai/context/CS-INDEX-021.md
```

Context Pack 自动收集：

- 根级 `AGENTS.md`；
- System Map；
- Dependency Rules；
- 目标模块 `MODULE.md`；
- `module.yaml`；
- Task；
- 引用的 ADR；
- 引用的 Contract；
- 目标模块文件树；
- Public API 签名；
- 相关测试名称；
- 目标模块最近 10 个 Commit；
- 当前分支、Base Commit、工作区 Diff；
- 依赖模块 Public Contract。

默认不收集：

- 整个仓库源码；
- 无关模块实现；
- 大型生成文件；
- Lock 文件；
- 全量日志；
- 旧版本文档；
- `node_modules`；
- 数据库；
- 构建产物。

---

## 14.3 Context Pack 大小预算

建议：

| 内容 | 上下文预算 |
|---|---:|
| 全局规则和系统图 | 10% |
| 目标模块文档和合同 | 20% |
| 当前任务与验收标准 | 15% |
| 目标代码和测试 | 45% |
| 临时分析余量 | 10% |

Context Pack 软限制：

```text
50,000～80,000 字符
```

超过限制时优先保留：

1. Task；
2. Public Contract；
3. 不变量；
4. 相关测试；
5. 当前 Diff；
6. 目标实现文件。

---

## 14.4 会话检查点

当上下文使用到约 60%～70%，或完成一个明显阶段时，AI 必须生成 Handoff。

不能等到窗口耗尽后才总结。

Handoff 必须写入文件：

```text
.ai/handoffs/CS-INDEX-021.md
```

格式：

```markdown
# Handoff: CS-INDEX-021

## Base
- Branch:
- Base Commit:
- Current Commit:

## 已完成
- ...

## 当前实现状态
- ...

## 修改文件
- ...

## 已通过测试
- ...

## 当前失败
- ...

## 已作决定
- ...

## 不得改变
- ...

## 下一步
1. ...
2. ...

## 风险
- ...

## 工作区状态
- clean / dirty
```

新会话只需要：

```text
Context Pack + Handoff + git diff
```

即可继续。

---

## 14.5 每次合并后压缩上下文

任务完成并合并后：

- 临时过程不写入 `MODULE.md`；
- 真正改变边界的内容更新 `MODULE.md`；
- 架构决定写 ADR；
- 合同变化更新 Contract；
- 项目状态更新 `PROJECT_STATE.md`；
- Task 移入 done；
- Handoff 归档；
- 生成新的 Module Map。

这样项目记忆不会随着任务数量无限膨胀。

---

# 15. AI 任务单设计

## 15.1 Task 必须足够小

一个 AI Task 建议满足：

- 只属于一个业务模块；
- 一次会话或一次短续会话可完成；
- 有明确输入和输出；
- 有确定测试；
- 不需要理解整个项目；
- 默认不修改超过一个模块；
- 软限制修改 5～15 个实现文件；
- 如果涉及两个以上模块，先拆 Contract Task。

---

## 15.2 Task 模板

```markdown
# CS-INDEX-021：实现分类库存完整快照校验

## 1. Base
- Repository: CloudSite
- Base Branch: v2/integration
- Base Commit: <sha>
- Module: indexing
- Owner: indexing-owner

## 2. 目标
实现 CategoryInventorySnapshot 的分页完整性校验。
任一分页缺失时不得调用 CatalogIngestPort。

## 3. 输入合同
- StorageInventoryPort v1
- CatalogIngestPort v1
- ADR-0012

## 4. 允许修改
- apps/api/cloudsite/modules/indexing/**
- apps/api/tests/system/fakes/storage.py
- docs/tasks/CS-INDEX-021.md

## 5. 禁止修改
- modules/catalog/infrastructure/**
- modules/storage/infrastructure/**
- shared_kernel/**
- 已发布 HTTP Contract
- 数据库迁移

## 6. 必须保持的不变量
- 不完整快照零写入
- 同一 Job 幂等
- Provider 限流不被绕过

## 7. 验收标准
- 第 1～N 页完整时生成 complete snapshot
- 第 N 页失败时删除临时 snapshot
- 不调用 CatalogIngestPort
- 重试不产生重复 snapshot item
- 服务重启后任务可恢复

## 8. 测试
```bash
pytest cloudsite/modules/indexing/tests/unit/test_snapshot.py
pytest cloudsite/modules/indexing/tests/integration/test_snapshot_job.py
```

## 9. 输出
- Commit
- Result/Handoff
- 测试结果
- 风险
```

---

## 15.3 AI 开工固定流程

```bash
git status
git branch --show-current
git log -5 --oneline
```

然后：

1. 校验 Base Commit；
2. 读取 Context Pack；
3. 读取允许修改路径；
4. 复述边界和验收标准；
5. 先运行相关测试；
6. 再开始修改；
7. 修改后运行模块测试；
8. 输出 Diff Summary；
9. 生成 Result/Handoff；
10. 提交到自己的分支。

---

# 16. 多人 / 多 Agent 协作模式

## 16.1 角色

### Architect / Integrator

负责：

- 系统蓝图；
- 模块边界；
- Data Ownership；
- Contract；
- ADR；
- Shared Kernel；
- Module Registry；
- Task 拆分；
- PR Review；
- 合并顺序；
- 版本和 GA 判断。

默认不直接承担大量模块实现。

### Module Owner

负责一个模块：

- 实现；
- 模块测试；
- 文档；
- 数据迁移；
- Contract 兼容；
- 模块健康状态；
- 该模块 PR 审核。

### Release / QA Owner

负责：

- 架构规则测试；
- Contract 测试；
- 系统集成测试；
- 数据迁移；
- Docker；
- amd64 / arm64；
- 升级、恢复、回滚；
- Release；
- README 和安装路径。

---

## 16.2 独立工作目录

每个 Agent 使用独立 Git Worktree：

```bash
git fetch origin

git worktree add ../cloudsite-indexing \
  -b mod/indexing/CS-INDEX-021 \
  origin/v2/integration

git worktree add ../cloudsite-catalog \
  -b mod/catalog/CS-CATALOG-014 \
  origin/v2/integration
```

禁止多个 Agent 共享同一个工作目录和未提交工作区。

---

## 16.3 分支策略

```text
main
└── 当前稳定发布线

release/1.x
└── 1.x 紧急维护

v2/integration
└── 2.0 持续集成分支

contract/<topic>/<task-id>
└── 先合并合同

mod/<module>/<task-id>
└── 模块实现

fix/<module>/<task-id>
└── 缺陷修复
```

模块不使用持续几个月的个人大分支。

一个模块由多个短 Task 分支组成，持续合并到 `v2/integration`。

---

## 16.4 AI-BUS 优化

可以使用独立：

```text
cloudsite-ai-bus/
├── tasks/
│   ├── queued/
│   ├── running/
│   ├── done/
│   └── blocked/
├── handoffs/
├── results/
└── status/
```

但以下内容不得复制到 AI-BUS：

- Contract；
- ADR；
- Module 文档；
- System Map；
- Data Ownership。

这些必须只存在于 CloudSite 主仓库，防止两份真相漂移。

AI-BUS 任务通过以下字段引用主仓库：

```text
repository
base_commit
module
task_id
contract_paths
adr_paths
allowed_paths
```

---

# 17. Contract First 并行开发流程

## 17.1 第一步：Architect 提交合同 PR

合同 PR 只包含：

- ADR；
- DTO；
- Port；
- Event Schema；
- Error Code；
- Fake；
- Contract Test；
- Module Manifest 更新。

不包含大规模业务实现。

---

## 17.2 第二步：各模块用 Fake 并行开发

例如：

```text
Storage Owner
→ 实现 AList Adapter
→ 通过 Storage Contract Test

Indexing Owner
→ 使用 FakeStorageInventoryPort
→ 实现分类库存任务

Catalog Owner
→ 使用 Fake Catalog Snapshot
→ 实现资源入库

Frontend Owner
→ 使用 OpenAPI Mock
→ 实现页面
```

各模块无需等待对方完整实现。

---

## 17.3 第三步：持续集成

每完成一个可工作的垂直切片就合并：

```text
合同
→ Fake
→ 模块实现
→ 模块合同测试
→ 集成测试
→ v2/integration
```

Feature 未完成时：

```text
CLOUDSITE_INDEX_ENGINE=legacy
CLOUDSITE_CATALOG_V2_READ=false
```

新代码可以存在，但不接管生产流量。

---

## 17.4 第四步：系统切换

建议 Feature Flag：

```text
storage_v2
catalog_v2_writes
catalog_v2_reads
indexing_v2
search_v2
delivery_v2
frontend_v2
```

切换顺序：

```text
Storage v2 Adapter
→ Catalog v2 Shadow Write
→ Indexing v2 Shadow Run
→ Search v2 Build
→ 对账
→ Catalog v2 Read
→ Delivery v2
→ Frontend v2
→ 停止 Legacy Write
→ 删除 Legacy
```

---

# 18. 架构边界自动化

## 18.1 Python Import 规则

CI 必须检查：

1. 模块只能导入其他模块的 `public`；
2. Domain 不依赖 FastAPI、SQLAlchemy、HTTPX；
3. API 不导入其他模块的 Infrastructure；
4. `shared_kernel` 不导入任何业务模块；
5. 不允许新增 `from cloudsite.main import ...`；
6. 不允许跨模块导入 ORM；
7. 不允许 Provider 原始 DTO 离开 Storage；
8. 不允许模块绕过 Port 直接访问其他 Schema。

可以通过 Architecture Test 实现：

```python
def test_no_module_imports_other_module_internals():
    ...

def test_domain_has_no_framework_imports():
    ...

def test_no_import_from_cloudsite_main():
    ...

def test_shared_kernel_has_no_business_dependencies():
    ...
```

也可以引入 Import Boundary 工具，但自动化规则本身必须纳入仓库，不依赖人工记忆。

---

## 18.2 前端 Import 规则

ESLint 检查：

```text
features/a 不得深层导入 features/b 内部
app 只导入 feature public entry
shared 不得导入 feature
generated 不得手工修改
feature 不得直接使用另一个 feature 的私有 Query Key
```

允许：

```ts
import { ResourceCard } from "@/features/catalog/public";
```

禁止：

```ts
import { ResourceCard } from "@/features/catalog/components/internal/ResourceCard";
```

---

## 18.3 文件体积规则

不是强制以行数判断质量，但需要预警：

| 文件类型 | 软限制 | 处理 |
|---|---:|---|
| Python / TypeScript 实现 | 500 行 | Review 是否职责过多 |
| 单文件硬警告 | 800 行 | 必须说明保留理由 |
| Router | 300 行 | 拆 Use Case |
| 单个 Route Handler | 50 行 | 业务下沉 |
| `MODULE.md` | 300 行 | 保留边界信息，细节拆 ADR |
| 全局 CSS | 15 KB | 业务样式迁出 |
| 生成代码 | 不限 | 标记 Generated，不人工修改 |

---

# 19. 测试架构

## 19.1 模块单元测试

只测试本模块 Domain 和 Use Case，使用 Fake Port。

特点：

- 快；
- 不启动 FastAPI；
- 不连接真实 AList；
- 不连接其他模块；
- 可单独运行。

---

## 19.2 Contract Test

每个 Port 同时有：

- Provider Contract Test；
- Consumer Contract Test。

例如所有 Storage Adapter 都必须通过：

```text
list_children 分页
空目录
Unicode
重复条目
不完整分页
429
认证失效
下载入口
Range Capability
```

Indexing 使用相同 Fake 行为验证自己。

---

## 19.3 模块集成测试

只启动：

```text
目标模块
PostgreSQL 测试 Schema
必要的 Fake 依赖
```

不启动完整系统。

---

## 19.4 系统集成测试

覆盖模块连接：

```text
Storage → Indexing → Catalog → Search
IAM → Sharing → Delivery
Catalog → Curation → Portal
IAM → User Library → Portal
```

---

## 19.5 E2E

保留少量最重要流程：

```text
首次安装
配置存储
建立内容根
索引分类
搜索资源
查看资源
下载
分享
收藏
升级
恢复
```

E2E 不代替模块测试。

---

## 19.6 CI 受影响模块矩阵

CI 根据 Git Diff 和 `module.yaml` 依赖图计算：

```text
修改 storage
→ 测 storage
→ 测 indexing contract
→ 测 delivery contract
→ 跑相关系统测试

修改 catalog public contract
→ 测 catalog
→ 测 search
→ 测 delivery
→ 测 sharing
→ 测 curation
→ 测 user_library
→ 测 portal
```

核心合同变化必须跑全量 CI。

---

# 20. 从 1.0 到 2.0 的文件迁移地图

| 1.0 文件 | 2.0 归属 |
|---|---|
| `main.py` | `bootstrap/app.py`，最终只保留一行入口 |
| `config.py` | `bootstrap/settings.py` + 模块配置 |
| `database.py` | `platform/db/*` |
| `migrations.py` | `platform/db/migration_runner.py` + 各模块 migrations |
| `models.py` | 各模块 `infrastructure/models.py` |
| `schemas.py` | 各模块 `api/*models.py` 和 `public/dto.py` |
| `auth.py` | `modules/iam/*` |
| `users.py` | `modules/iam/api/admin_router.py` 等 |
| `sessions.py` | `modules/iam/application` + `infrastructure` |
| `admin_auth.py` | `modules/iam` |
| `site.py`、`site_assets.py` | `modules/site` |
| `alist.py`、`providers/*` | `modules/storage` |
| `identity/*` | Resource Identity 归 `catalog`，发现匹配策略归 `indexing` |
| `indexer.py`、`sync/*` | 旧代码冻结；新实现归 `modules/indexing` |
| `search.py` | `modules/search` |
| `download.py`、`preview.py`、`office.py` | `modules/delivery` |
| `download_rate_limit.py` | `modules/delivery` |
| `shares/*` | `modules/sharing` |
| `routers/resources.py` | `catalog/api` + `delivery/api` |
| `routers/search.py` | `search/api` |
| `routers/downloads.py`、`previews.py` | `delivery/api` |
| `routers/shares.py` | `sharing/api` |
| `services/resources.py` | Catalog Query/DTO；不再只是序列化工具 |
| `userdata.py` | `modules/user_library` |
| Collection 相关 | `modules/curation` |
| Submission 相关 | `modules/contributions` |
| Notification 相关 | `modules/communications` |
| Admin Overview/Diagnostics/System | `modules/operations` |
| Home Router | `modules/portal` |
| `tasks/scheduler.py` | `platform/jobs`，只调模块公开 Job Port |

---

# 21. 渐进式迁移方案

## 21.1 Phase 0：冻结 1.0

完成：

- `v1.0.0` Tag 保持不可变；
- 创建 `release/1.x`；
- 创建 `v2/integration`；
- 1.x 只接受安全、数据丢失和严重兼容 Bug；
- 新功能进入 2.0；
- 备份当前 OpenAPI、数据库 Schema 和核心 E2E 结果。

---

## 21.2 Phase 1：建立模块化基础设施

任务：

1. 增加 `AGENTS.md`；
2. 增加 System Map、Dependency Rules、Data Ownership；
3. 增加 ADR 目录；
4. 增加 Module Manifest Schema；
5. 增加 `bootstrap/`；
6. 增加 `AppContainer`；
7. 增加显式 Module Registry；
8. 增加 Architecture Tests；
9. 增加 Context Pack 工具；
10. 增加 Task 和 Handoff 模板。

这一阶段不改变业务行为。

---

## 21.3 Phase 2：拆出基础模块

优先并行：

```text
iam
site
storage
catalog skeleton
```

要求：

- 先保留旧 HTTP 路由兼容；
- 新模块内部使用 Port；
- 旧文件可以暂时 re-export；
- 每完成一个模块就停止在旧文件增加新逻辑。

---

## 21.4 Phase 3：实现新索引架构

完全按照 `新架构开发文档.md` 新建：

```text
modules/indexing/
```

不要从 `rolling.py` 继续扩展。

并行工作：

- Storage Owner：分页、Provider DTO、请求治理；
- Catalog Owner：资源、分类、Manifest、稳定身份；
- Indexing Owner：库存快照、任务、补全、熔断；
- Search Owner：PostgreSQL 搜索投影；
- Operations Owner：状态和诊断；
- Frontend Owner：后台任务和资源状态页面。

---

## 21.5 Phase 4：迁移外围业务

按依赖顺序：

```text
delivery
sharing
curation
user_library
contributions
communications
portal
```

每个模块迁移后：

- 旧路由进入只读兼容或转发；
- 新写入只走新模块；
- 运行数据对账；
- Feature Flag 控制切换；
- 保留明确回滚路径。

---

## 21.6 Phase 5：前端 Feature 化

顺序：

1. `shared/api` 和生成类型；
2. `shared/ui`；
3. IAM；
4. Catalog；
5. Search；
6. Delivery；
7. Sharing；
8. User Library；
9. Curation；
10. Admin Operations；
11. 清理 `globals.css`；
12. 删除旧 `lib/api.ts` 中领域 DTO。

---

## 21.7 Phase 6：删除 Legacy 桥梁

只有满足以下条件才删除：

- v2 完整回归通过；
- 数据迁移演练通过；
- v1 到 v2 升级通过；
- 回滚演练通过；
- 新索引连续运行稳定；
- 旧 API 已有迁移说明；
- 所有 `from cloudsite.main import` 已消失；
- 无跨模块 ORM Import；
- 旧 `models.py`、`schemas.py`、`rolling.py` 不再被生产入口引用。

---

# 22. 首批建议任务

```text
CS-MOD-001  创建 AGENTS.md 和架构文档入口
CS-MOD-002  定义 module.yaml Schema
CS-MOD-003  实现 Architecture Import Tests
CS-MOD-004  建立 bootstrap/AppContainer/ModuleRegistry
CS-MOD-005  建立 Context Pack 和 Handoff 工具
CS-STORAGE-001 冻结 Storage Public Contract
CS-CATALOG-001 冻结 Catalog Public Contract
CS-INDEX-001 冻结 Indexing Public Contract
CS-SEARCH-001 冻结 Search Event Contract
CS-DB-001 建立 PostgreSQL Schema 与模块 Migration Runner
CS-IAM-001 将 Auth 路由迁入 IAM，不改变行为
CS-STORAGE-002 实现 Generic AList Adapter v2
CS-CATALOG-002 建立 Category/Resource/ResourceFile Model
CS-INDEX-002 建立 PostgreSQL Sync Job Queue
CS-INDEX-003 实现分类库存快照
CS-INDEX-004 实现资源 Manifest 补全
CS-SEARCH-002 实现 Resource Search Projection
CS-WEB-001 建立 Feature 目录与 Generated API
CS-QA-001 建立模块 CI 矩阵
```

前五项是所有并行开发的前置条件。

---

# 23. Definition of Done

一个模块只有满足以下条件才算完成：

## 23.1 结构

- 有 `module.yaml`；
- 有 `MODULE.md`；
- 有单一公开入口；
- 无跨模块内部导入；
- 无 `cloudsite.main` 依赖；
- 无共享 ORM Model；
- 无原始 Provider DTO 泄露。

## 23.2 合同

- HTTP Contract 已版本化；
- Internal Port 已版本化；
- Event 已版本化；
- Error Code 已登记；
- 兼容性变化有 ADR；
- 前端生成类型已更新。

## 23.3 数据

- 数据表有明确所有者；
- Migration 可重复执行；
- 升级前检查存在；
- 数据迁移有对账；
- 失败有回滚或恢复策略；
- 不直接跨 Schema 写入。

## 23.4 测试

- Domain Unit Test；
- Application Use Case Test；
- Contract Test；
- Module Integration Test；
- 必要的 System Test；
- Architecture Test；
- 安全边界测试。

## 23.5 运维

- Health；
- 日志；
- Error Code；
- 关键指标；
- 管理员诊断；
- Feature Flag；
- 回滚说明。

## 23.6 AI 交接

- Task 已完成；
- Result 已记录；
- Handoff 已归档；
- MODULE.md 在必要时更新；
- ADR/Contract 与实现一致；
- 工作区干净；
- Commit 可定位。

---

# 24. 模块化验收指标

CloudSite 2.0 模块化改造完成后，应达到：

```text
1. 新 Agent 在 10 分钟内进入目标模块开发；
2. 新会话无需重新读取整个仓库；
3. 普通 Task 默认只修改一个业务模块；
4. 任何模块都能独立运行 Unit 和 Contract Test；
5. 其他模块只能导入 public；
6. 不存在生产代码对 cloudsite.main 的反向依赖；
7. 不存在全局 models.py 和 schemas.py 业务聚合；
8. 不存在超过 800 行而无说明的手写核心文件；
9. Router 不直接执行复杂 SQL 和业务编排；
10. Provider 原始 JSON 不离开 Storage；
11. 数据表 100% 有唯一模块所有者；
12. 合同变化可以自动识别受影响模块；
13. 多 Agent 同时开发时，共享文件冲突显著减少；
14. v2/integration 始终可启动、可测试；
15. 最终发布前不需要进行第一次全系统集成。
```

---

# 25. 禁止事项

## 25.1 禁止重新制造超级共享层

禁止把不知归属的代码全部放进：

```text
shared/
common/
utils/
helpers/
base/
```

进入 Shared Kernel 的条件：

- 与业务无关；
- 至少两个模块真正需要；
- 语义长期稳定；
- 不包含 ORM；
- 不包含 FastAPI；
- 不包含 Provider；
- 不包含业务状态；
- 经架构师批准。

---

## 25.2 禁止把模块化理解为“多建几个文件夹”

真正模块必须有：

- Ownership；
- Contract；
- Data Boundary；
- Dependency Rule；
- Tests；
- Documentation。

只有目录，没有边界检查，最终仍会回到耦合单体。

---

## 25.3 禁止一个 Task 同时重构全项目

禁止任务：

```text
把整个后端模块化
重写所有 Schema
统一所有 Service
一次性迁移所有表
一次性改完前后端
```

必须拆成可验证的小 Task。

---

## 25.4 禁止一次性最终合并

模块开发必须持续集成。

任何模块分支超过数天仍未合并，应检查：

- Task 是否过大；
- Contract 是否未冻结；
- 是否需要拆 Feature Flag；
- 是否在修改共享文件；
- 是否应该拆成多个 PR。

---

## 25.5 禁止让 AI 以聊天记忆作为依据

AI 不得说：

```text
我记得之前决定过……
```

必须定位：

```text
ADR
Contract
MODULE.md
Task
Commit
```

找不到就视为未正式决定。

---

## 25.6 禁止为模块化立即拆微服务

只有同时出现以下需求时才评估服务拆分：

- 模块需要独立伸缩；
- 模块需要独立发布；
- 模块有独立数据生命周期；
- 模块故障必须隔离；
- 单体进程成为真实瓶颈；
- 团队有能力承担分布式运维；
- Contract 已经长期稳定。

在此之前继续保持模块化单体。

---

# 26. 推荐的实际协作示例

假设同时有五个 Agent：

```text
Architect
├── 冻结 Storage/Catalog/Indexing Contract
├── 维护 ADR 和 Module Map
└── Review / Merge

Agent A：Storage
├── AList Adapter
├── Pagination
├── Request Budget
└── Provider Contract Tests

Agent B：Catalog
├── Category
├── Resource
├── Manifest
└── Stable ID

Agent C：Indexing
├── Job Queue
├── Category Snapshot
├── Hydration
└── Reconciliation

Agent D：Search / Portal
├── Search Projection
├── Search API
└── Home Read Model

Agent E：QA / Release
├── PostgreSQL Migration
├── Contract Matrix
├── Integration Tests
└── Docker / Upgrade / Recovery
```

并行前先合并：

```text
StorageInventoryPort
CatalogIngestPort
IndexingCommandPort
ResourceUpsertedV1
Fake 实现
```

之后各 Agent 不需要读取对方内部代码。

---

# 27. 最终建议

CloudSite 当前最需要的不是继续增加更多功能文件，而是建立一套让代码规模增长后仍然可控制的开发操作系统。

最终开发模式应变成：

```text
架构师定义蓝图
        ↓
冻结模块边界和合同
        ↓
生成独立 Task 和 Context Pack
        ↓
一个 Owner 负责一个模块
        ↓
Agent 只读取目标模块和 Public Contract
        ↓
模块独立实现和测试
        ↓
短分支持续合并到 v2/integration
        ↓
系统测试持续运行
        ↓
Feature Flag 分阶段切换
        ↓
发布时只启用成熟模块
```

最重要的三个结论：

1. **当前 1.0 是“有拆分的单体”，不是“可独立交付的模块化单体”。**
2. **解决 AI 上下文问题的关键不是扩大上下文窗口，而是让每个任务只需要一个模块的上下文，并把所有长期决定写入 Git。**
3. **可以一人负责一个模块，但必须 Contract First、短分支、持续集成，不能等全部开发完成后才第一次组合。**

CloudSite 2.0 的第一步不应直接修改旧 `rolling.py`，而应先完成：

```text
AGENTS.md
System Map
Module Manifest
Dependency Rules
AppContainer
Module Registry
Architecture Tests
Context Pack
Task/Handoff 模板
```

这些基础完成后，再让多个 Agent 分别开发 Storage、Catalog、Indexing、Search、Delivery 等模块，项目规模继续增长时，AI 开发难度才不会同步失控。
