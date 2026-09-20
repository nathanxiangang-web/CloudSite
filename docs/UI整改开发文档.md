# CloudSite 后台 UI 整改开发文档

> 状态：Active  
> 适用分支：`main`  
> 创建日期：2026-09-20  
> 适用范围：CloudSite Web 管理后台（`apps/web/src/app/admin/**`）  
> 关联方向：Issue #157 P3（产品/UI/E2E 阶段）  
> 文档性质：当前 UI 整改实施规范，不是历史设计稿。若本文与运行时代码冲突，以当前 `main` 的代码、测试和真实 API 行为为准。

---

## 1. 文档目标

CloudSite 已结束以“大规模模块化迁移”为主的开发阶段，当前后台具备较完整的功能页面和基础视觉语言，但随着管理功能增长，出现以下问题：

- 左侧导航入口持续增加，信息架构开始失去层次；
- 多数页面采用“标题 + 多个白色 Panel”的同构布局，页面之间缺少明确的工作模式区分；
- Dashboard 已有数据，但尚不能快速回答“系统是否正常、是否有待处理事项、最近发生了什么”；
- 内容索引页功能基础较好，但同步状态、开发术语、异常状态和运行语义仍需收口；
- System、Presentation 等配置页开始承载过多职责，继续叠加会迅速恶化可用性；
- 表格、Toolbar、Badge、Empty/Error/Loading、分页、危险操作等交互模式尚未完全统一；
- `apps/web/src/app/globals.css` 已同时承载前台、后台、Catalog、通知、动画和响应式样式，继续增长会提高回归风险；
- 后端 Indexing/Search 已进入真实生产路径，但部分 UI 所需的“运行进度”并不存在，前端不能通过视觉包装伪造后端没有提供的数据。

本次整改的目标不是重做一套炫酷后台，而是把现有后台收口成一个稳定、克制、高信息密度、适合长期维护的 **CloudSite Control Center**。

核心目标：

1. 建立统一后台信息架构；
2. 建立统一 Admin Shell 和页面模板；
3. 优先完成 Dashboard、内容索引、System、Presentation 四个核心页面；
4. 建立可复用的后台 UI 组件和状态语义；
5. 保持当前业务 API 和模块边界，不借 UI 整改重新发起后端大重构；
6. 为 P3c 后续 browse/search/resource/folder/share/admin UI 一致性改造提供基线；
7. 建立可重复的 E2E 验收路径，避免“页面存在即完成”。

---

## 2. 设计定位

### 2.1 产品定位

后台定位为：

> **CloudSite Control Center — 内容、运行、用户和站点的统一控制台。**

后台主要用户不是消费者，而是站点管理员、内容管理员和维护者，因此设计优先级为：

```text
正确性 > 可读性 > 操作效率 > 一致性 > 视觉装饰
```

### 2.2 视觉方向

推荐参考的产品气质：

- GitHub Settings；
- Vercel Dashboard；
- Linear 的克制型工作台；
- 现代 SaaS 管理后台。

保留当前 CloudSite 已经形成的基础风格：

- 蓝色作为主要强调色；
- 浅灰页面背景；
- 白色工作区域；
- Lucide 图标；
- 轻边框；
- 小范围柔和阴影；
- 12–14px 辅助信息；
- 中等信息密度；
- 明暗主题继续共用同一套语义 Token。

### 2.3 明确不做

本轮不做：

- 大屏可视化风格；
- 玻璃拟态；
- 大面积渐变；
- 高频背景动画；
- 为“科技感”增加无信息价值动效；
- 超大 KPI 数字占据首屏；
- 为 UI 整改重写后端模块；
- 为统一风格强行引入大型第三方 UI 框架；
- 为了“组件化”把简单页面切成大量微组件；
- 在后端不存在 total/progress 的情况下伪造百分比进度；
- 暂不把后台改造成独立微前端。

---

## 3. 当前实现审计

### 3.1 当前 Shell

当前后台入口由：

`apps/web/src/components/AdminShell.tsx`

提供：

- 固定左侧导航；
- Brand；
- 页面标题；
- 登出按钮；
- 管理员认证状态检查；
- 返回前台入口。

该基础结构可继续沿用，不需要推翻。

当前主要问题：

1. 13 个一级入口全部平铺；
2. 没有导航分组；
3. 顶部 Header 只承担“页面标题 + 退出”，信息价值偏低；
4. 返回前台和退出操作分散；
5. 缺少全局系统状态、通知、管理员身份等可选状态位；
6. 页面标题没有副标题/面包屑层级；
7. 移动端 Shell 需要进一步明确收起方式。

### 3.2 当前主要管理页

当前主要后台页面包括：

- `/admin` 概览；
- `/admin/index` 内容索引；
- `/admin/collections` 精选合集；
- `/admin/catalog` 目录管理；
- `/admin/automation` 整理工作台；
- `/admin/shares` 分享管理；
- `/admin/submissions` 投稿审核；
- `/admin/notifications` 通知管理；
- `/admin/users` 用户管理；
- `/admin/diagnostics` 下载诊断；
- `/admin/presentation` 站点呈现；
- `/admin/site` 网站设置；
- `/admin/system` 系统。

功能覆盖已经足够广，当前主要问题不再是“缺页面”，而是：

> 页面之间缺少统一的工作模式和层级组织。

### 3.3 当前样式基础

`apps/web/src/app/globals.css` 已经存在：

- `.admin-shell`
- `.admin-sidebar`
- `.admin-main`
- `.admin-page`
- `.stat-grid`
- `.panel`
- `.admin-columns`
- `.admin-tabs`
- `.small-search`
- `.index-summary-grid`
- `.index-workspace`
- `.folder-tree-*`
- 多类表格、Badge、表单和响应式规则。

这些都应当优先复用和收口，而不是全部删除重写。

---

## 4. 目标后台信息架构

### 4.1 一级导航重组

当前一级导航不再全部平铺，调整为以下结构：

```text
概览

内容
  内容索引
  目录管理
  精选合集
  整理工作台
  投稿审核

运营
  分享管理
  用户管理
  通知管理

运行
  下载诊断

站点
  站点呈现
  网站设置

配置
  系统设置
```

### 4.2 导航原则

每个入口只能属于一个主要工作域。

不允许新增类似：

```text
其他
工具
更多
高级功能
```

这种无法表达领域含义的垃圾桶分组。

### 4.3 导航排序规则

排序依据：

1. 使用频率；
2. 生产关键性；
3. 管理员心智模型；
4. 数据生命周期顺序。

内容域推荐顺序：

```text
索引 → 目录 → 合集 → 整理 → 投稿
```

因为其语义接近：

```text
发现资源 → 组织资源 → 聚合展示 → 自动整理 → 外部输入
```

---

## 5. Admin Shell 目标设计

### 5.1 桌面端结构

```text
┌──────────────────┬──────────────────────────────────────────────────────┐
│ CloudSite        │ 内容 / 内容索引                     通知  管理员     │
│ Control Center   │ 内容索引                                             │
│                  │ 扫描和管理 CloudSite 中的资源                        │
│ 概览             ├──────────────────────────────────────────────────────┤
│                  │                                                      │
│ 内容             │                    页面内容                          │
│  内容索引        │                                                      │
│  目录管理        │                                                      │
│  精选合集        │                                                      │
│  整理工作台      │                                                      │
│  投稿审核        │                                                      │
│                  │                                                      │
│ 运营             │                                                      │
│  ...             │                                                      │
│                  │                                                      │
│ ● 系统正常       │                                                      │
│ 返回网站         │                                                      │
│ 管理员 / 退出    │                                                      │
└──────────────────┴──────────────────────────────────────────────────────┘
```

### 5.2 Sidebar

Sidebar 保持固定宽度，但增加：

- 分组标签；
- 当前路由高亮；
- 一级项目图标；
- Footer 状态；
- 返回前台；
- 用户/退出区域。

建议：

- 分组 Label 使用 10–11px；
- 导航项目 40–44px 高；
- Active 使用蓝色软背景，不使用大面积纯蓝块；
- Hover 与 Active 必须有区别；
- Sidebar Footer 不能抢占主导航注意力。

### 5.3 Header

Header 从：

```text
页面标题                              退出
```

调整为：

```text
内容 / 内容索引                      [通知] [管理员]
内容索引
扫描和管理 CloudSite 中的资源
```

建议组件：

```tsx
<AdminPageHeader
  breadcrumb={["内容", "内容索引"]}
  title="内容索引"
  description="扫描和管理 CloudSite 中的资源"
  actions={...}
/>
```

重要：

- 页面级主操作优先放 Header；
- Panel 内操作只属于局部对象；
- 同一页面不要同时在 Header 和 Panel 重复放“保存/同步”等主动作。

### 5.4 移动端 Shell

小屏幕下：

- Sidebar 不固定占宽；
- 使用顶部菜单按钮打开 Drawer；
- Drawer 展示完整分组导航；
- Header 保留标题和主要动作；
- 非关键副标题允许隐藏；
- 页面内容使用 16px 左右边距；
- 表格优先横向滚动，不强行压缩所有列。

---

## 6. 页面模板规范

后台只保留三类主要页面模板。

### 6.1 Dashboard Template

适用：

- 概览；
- 下载诊断；
- 后续运行状态页。

结构：

```text
Page Header
↓
KPI / Health Summary
↓
Primary Status
↓
Attention Required
↓
Recent Activity / Trend
```

### 6.2 Workspace Template

适用：

- 内容索引；
- Catalog；
- Automation；
- 投稿审核；
- 分享管理；
- 用户管理。

结构：

```text
Page Header + Primary Action
↓
Toolbar / Filter
↓
Main Work Area
↓
Optional Detail Panel / Drawer
```

Workspace 不应由 5–8 个同权重 Panel 纵向堆叠。

### 6.3 Settings Template

适用：

- System；
- Site；
- Presentation 的部分设置；
- 后续安全设置。

结构：

```text
Page Header
↓
┌──────────────┬──────────────────────────────┐
│ 设置导航     │ 当前设置                     │
│              │                              │
│ 数据源       │                              │
│ 内容根目录   │                              │
│ 同步策略     │                              │
│ ...          │                              │
└──────────────┴──────────────────────────────┘
```

---

## 7. Dashboard（/admin）整改

### 7.1 Dashboard 要回答的问题

管理员进入后台后，优先回答：

1. 系统现在是否正常？
2. 内容数据是否新鲜？
3. 是否有必须处理的事项？
4. 最近发生了什么？
5. 是否需要立即同步或排查异常？

### 7.2 第一屏推荐结构

```text
概览                                      系统正常 ●
最后同步 16:42 · 自动同步已开启

┌───────────┬───────────┬───────────┬──────────────────┐
│ 125,420   │ 8,231     │ 3         │ AList            │
│ 资源      │ 目录      │ 待处理    │ ● 已连接          │
└───────────┴───────────┴───────────┴──────────────────┘

┌───────────────────────────────────────────────────────┐
│ 内容同步                                  [立即同步]  │
│ ● 正常                                                │
│ 最近同步 16:42 · +142 新增 · ~23 修改 · -7 删除     │
│ 耗时 4m32s                                            │
└───────────────────────────────────────────────────────┘

┌────────────────────────┬──────────────────────────────┐
│ 待处理                 │ 最近活动                    │
│ 12 条整理建议          │ 16:42 索引完成              │
│ 3 条投稿待审核         │ 16:38 创建分享              │
│ 2 个下载异常           │ 16:20 发布 Catalog          │
└────────────────────────┴──────────────────────────────┘
```

### 7.3 KPI 原则

KPI 不超过 4 个主卡片。

推荐：

- 资源；
- 目录；
- 待处理；
- 数据源状态。

“下载异常”如果为 0，不需要永远占一个红色 KPI，可进入运行状态/待处理区域。

### 7.4 待处理聚合

未来可由多个业务源聚合：

- Automation pending；
- Submission pending；
- 下载异常；
- 失败同步；
- 数据源断开；
- Search dirty/recovery 状态。

初期不要求一次全部实现；先以现有 API 能提供的数据为准。

### 7.5 不做虚假健康评分

禁止：

```text
健康度 97分
系统评分 A+
```

除非有明确计算公式和可解释指标。

优先展示具体事实。

---

## 8. 内容索引（/admin/index）专项整改

该页面是后台现有结构最成熟的页面，应作为 Workspace 模板基准。

### 8.1 页面命名

界面主文案不要直接以：

```text
Indexing v2
```

作为主要管理员语言。

调整为：

```text
内容同步
从已启用的数据源扫描目录并更新 CloudSite 内容索引
```

“Indexing v2”只允许出现在：

- 高级信息；
- 调试信息；
- 诊断；
- 日志。

### 8.2 页面结构

```text
内容索引

┌──────────────┬──────────────┬─────────────────────────┐
│ 索引资源     │ 目录         │ 最近同步                │
│ 125,420      │ 8,231        │ 正常 · 2 分钟前         │
└──────────────┴──────────────┴─────────────────────────┘

┌───────────────────────────────────────────────────────┐
│ 内容同步                                  [立即同步]  │
│ AList · 3 个已启用内容根                               │
│ ● 索引正常                                             │
│ 最近同步：今天 16:42 · 3m18s                          │
└───────────────────────────────────────────────────────┘

┌──────────────────────────────────┬────────────────────┐
│ 目录                             │ 目录详情           │
│ [搜索已索引目录]                 │                    │
│ ▼ 软件                           │ 软件               │
│   ▼ Windows                      │ /Software          │
│      Adobe                       │ 资源 1423          │
│      Tools                       │ 子目录 43          │
│   ▶ Android                      │ 最近索引 16:42     │
│                                  │ 状态 正常          │
└──────────────────────────────────┴────────────────────┘
```

### 8.3 同步运行状态

当前后端无法提供真实“总文件数”，因此 **第一阶段禁止百分比进度条**。

允许展示：

- 已完成 root / 总 root；
- 当前路径；
- 已发现条目数；
- 已耗时；
- 当前状态。

示例：

```text
正在扫描
/Software/Windows/Adobe

已完成 2 / 3 个内容根
已发现 83,421 项
已运行 2m41s
```

后端以后若提供可靠 total 才增加百分比。

### 8.4 同步结束状态

展示：

- success / partial / failed / cancelled / skipped；
- added；
- changed；
- removed；
- unchanged 可放高级详情；
- duration。

状态色语义：

- success：green；
- running：blue；
- partial：amber；
- failed：red；
- cancelled：neutral；
- skipped：neutral。

### 8.5 自动同步与手动同步

UI 必须统一读取“真实运行状态”。

当前整改依赖后端把自动同步、启动同步、手动同步统一表达为同一运行状态。

禁止仅根据前端本地 mutation 判断同步中。

### 8.6 Cancel 语义

当前只有可取消任务句柄时才能展示“取消同步”。

若 Scheduler/Startup 运行没有可取消句柄：

- 不展示假的“取消”；
- 显示“自动同步正在运行”；
- 可提供“查看详情”。

### 8.7 目录树

保留当前左树右详情结构。

优化：

- Root 使用更明显视觉；
- Tree 行最小点击区 40px；
- 展开按钮和选择按钮保持独立；
- 搜索命中状态高亮关键词；
- 目录层级线保持低对比；
- 深层目录避免横向无限缩进，可设置最大视觉缩进并通过层级线表示；
- 超大量目录后续再考虑虚拟列表，不在第一阶段引入。

### 8.8 目录详情

详情区域统一定义：

- 名称；
- Path；
- Content Type；
- Root；
- Depth；
- Child Folder Count；
- Direct Resource Count；
- Modified At；
- Indexed At；
- Status。

不直接展示无意义内部 ID，除非点击“高级信息”。

### 8.9 异常状态

必须覆盖：

- Summary API 失败；
- Root Mapping API 失败；
- Folder list 失败；
- Detail 失败；
- 无内容根；
- 有内容根但未同步；
- 同步失败；
- partial；
- 后端 stale running 恢复后的 interrupted/failed。

---

## 9. System（/admin/system）整改

### 9.1 问题

System 当前同时承担：

- AList 连接；
- 内容根映射；
- 同步配置；
- 部分系统状态。

继续纵向堆 Panel 会迅速失控。

### 9.2 目标 IA

```text
系统设置

数据源
内容根目录
同步策略
存储与维护
安全
高级
```

初期只实现现有功能对应的导航，不需要为了凑栏目新增后端功能。

### 9.3 Settings Layout

```text
┌──────────────┬─────────────────────────────────────────┐
│ 数据源       │ AList 连接                              │
│ 内容根目录   │                                         │
│ 同步策略     │ ● 已连接                                │
│ 高级         │                                         │
│              │ 地址     https://...                    │
│              │ 用户名   admin                          │
│              │ 密码     已保存                         │
│              │                         [测试] [保存]    │
└──────────────┴─────────────────────────────────────────┘
```

### 9.4 数据源页

状态优先：

```text
● 已连接
https://alist.example.com
最后测试：刚刚
```

表单只用于修改。

“测试连接”和“保存”行为必须区分。

### 9.5 内容根目录

建议改成结构化列表：

```text
名称       类型      路径                状态     操作
软件       software  /Software           ●启用    编辑
教程       document  /Tutorials          ●启用    编辑
旧文件     file      /Archive             已停用   编辑
```

新增和编辑可以使用 Modal/Drawer，不必把表单永远铺在列表底部。

### 9.6 同步策略

集中展示：

- automatic sync；
- interval；
- sync on startup；
- 当前状态；
- 下次预计调度时间（仅当后端可可靠计算时展示）。

`full` / `force` 当前后端若没有真实语义，不在 UI 中新增高级开关。

---

## 10. Presentation（/admin/presentation）整改

### 10.1 当前问题

当前页面主要是：

- preset select；
- color input；
- radius number；
- 导航 input；
- ↑ / ↓；
- 文字版 Preview；
- revision 列表。

功能可用，但普通管理员难以直观看到最终站点效果。

### 10.2 目标模式

Presentation 调整为 **配置 + 实时预览工作台**。

```text
┌──────────────────────────────┬──────────────────────────────┐
│ 页面配置                     │ 实时预览                     │
│                              │                              │
│ 主题                         │ ┌──────────────────────────┐ │
│ 主题色                       │ │ CloudSite                │ │
│ 圆角                         │ │                          │ │
│                              │ │ 搜索资源...              │ │
│ 导航                         │ │                          │ │
│ ☰ 首页                       │ │ 推荐资源                 │ │
│ ☰ 软件                       │ │ □ □ □ □                  │ │
│                              │ └──────────────────────────┘ │
│ 首页区块                     │                              │
│ ☰ 精选推荐 ✓                 │ Desktop / Mobile            │
│ ☰ 最近更新 ✓                 │                              │
│                              │                              │
│ [保存草稿] [保存并发布]      │                              │
└──────────────────────────────┴──────────────────────────────┘
```

### 10.3 第一阶段实现边界

不用立刻开发完整 iframe 页面编辑器。

第一阶段可以：

- 基于当前 config 本地渲染轻量 Preview；
- 展示主题色；
- 展示圆角；
- 展示导航；
- 展示区块顺序；
- Desktop/Mobile 两种 Preview 宽度。

### 10.4 排序交互

当前 ↑ / ↓ 可保留作为无障碍 fallback。

后续可增加 drag handle：

```text
☰ 精选推荐
```

拖拽必须：

- 同时支持键盘替代；
- 保存前显示未保存状态；
- 排序不应触发立即发布。

### 10.5 发布语义

推荐区分：

- 本地未保存；
- 已保存未发布（如果后端未来支持）；
- 已发布；
- 发布失败；
- 回退。

若后端目前保存即发布，则 UI 不伪造“草稿”状态，只使用：

```text
保存并发布
```

### 10.6 Revision

历史 Revision 使用紧凑列表或 Timeline：

- revision；
- preset；
- summary；
- created_at；
- rollback。

危险回退操作需要二次确认。

---

## 11. Catalog / Automation / Submissions Workspace 收口

### 11.1 统一工作台语法

三类页面都应逐步收口为：

```text
Page Header
Toolbar
Data View
Detail
Bulk Actions
```

### 11.2 Catalog

Catalog 重点：

- 条目列表；
- Filter；
- Search；
- 状态；
- Detail；
- Release / Asset 关系。

减少“列表页 + 多个管理 Panel”混杂。

推荐 Detail 单独路由继续保留。

### 11.3 Automation

现有建议列表基础较完整。

整改重点：

- Filter Toolbar 固定为统一组件；
- Bulk selection 行为统一；
- confidence / status 使用统一 Badge；
- “应用/拒绝/撤销”使用统一 Action 样式；
- 建议详情优先使用 Detail Drawer，而不是页面底部再堆一个“前 10 条详情” Panel；
- JSON Evidence 可折叠显示。

### 11.4 Submissions

重点：

- pending 默认优先；
- 审核动作固定在同一区域；
- 状态 Badge 统一；
- 危险删除与“拒绝投稿”语义分离；
- 审核失败不静默；
- 列表空态给出明确含义，不只显示“暂无”。

---

## 12. Shares / Users / Notifications

### 12.1 Shares

建议统一为表格 Workspace：

Toolbar：

- 搜索；
- 状态；
- 类型；
- 创建时间。

行信息：

- share；
- target；
- owner；
- scope；
- status；
- expires；
- action。

### 12.2 Users

用户管理以“搜索 + 列表 + Detail”作为主结构。

危险操作：

- 禁用；
- 删除；
- 重置敏感状态；

必须二次确认，并显示影响范围。

### 12.3 Notifications

通知管理不应和前台通知 Popover 的视觉实现混用。

后台关注：

- level；
- audience；
- status；
- created；
- publish；
- delete。

---

## 13. Diagnostics

Diagnostics 属于运行 Dashboard，而不是普通 CRUD 表格。

推荐结构：

```text
运行诊断

下载请求成功率
最近失败数
Provider 状态

最近异常
失败原因分布
最近事件
```

禁止使用没有统计依据的图表。

如果后端只有事件列表，就先做事件列表，不制造趋势线。

---

## 14. 通用组件规范

建议新增目录：

```text
apps/web/src/components/admin/
├── AdminPageHeader.tsx
├── AdminSection.tsx
├── AdminStatCard.tsx
├── AdminStatusBadge.tsx
├── AdminToolbar.tsx
├── AdminEmptyState.tsx
├── AdminErrorState.tsx
├── AdminLoadingState.tsx
├── AdminConfirmDialog.tsx
├── AdminSettingsNav.tsx
└── AdminDetailDrawer.tsx
```

注意：

- 只抽取至少 2–3 个页面真实复用的模式；
- 不提前设计大型 Design System；
- 不做 `ButtonPrimaryBlueSmall` 等过度细组件；
- 简单页面局部组件继续放页面文件即可。

---

## 15. 状态组件统一

### 15.1 Status Badge

语义 Token：

```text
info      blue
success   green
warning   amber
danger    red
neutral   gray
```

业务状态映射在业务层完成，例如：

```ts
sync:
running   -> info
success   -> success
partial   -> warning
failed    -> danger
cancelled -> neutral
skipped   -> neutral
```

不要在 CSS 中根据字符串状态到处散落独立颜色。

### 15.2 Loading

禁止所有页面都只显示：

```text
正在加载...
```

推荐：

- 首次整页：Skeleton / Panel Loading；
- Query refresh：保留旧数据，显示局部 refresh；
- Button mutation：按钮 spinner + disabled；
- 不因后台轮询造成页面闪烁。

### 15.3 Empty

Empty State 至少回答：

1. 为什么为空？
2. 下一步可以做什么？

示例：

```text
尚未配置内容根目录
配置至少一个内容根目录后即可开始索引。
[前往系统设置]
```

### 15.4 Error

错误必须：

- 可见；
- 保留已有数据时不清空；
- 提供 retry；
- 不使用 `.catch(() => {})` 吞掉关键 UI 路径失败。

---

## 16. 表格规范

统一：

- Header；
- Row 高度；
- Hover；
- Selection；
- Pagination；
- Bulk action；
- Empty；
- Error；
- Horizontal scroll。

### 16.1 表格最小规则

- 主要名称列 `minmax(240px, 1fr)`；
- 状态列尽量固定宽；
- 操作列右对齐；
- ID 默认缩略；
- 时间统一 `zh-CN` 格式；
- 不允许不同页面同一个状态有不同颜色。

### 16.2 移动端

复杂后台表格不要强制 Card 化。

允许：

```css
overflow-x: auto
```

同时给主要列设置合理最小宽度。

---

## 17. 表单规范

### 17.1 Field

统一组成：

```text
Label
Control
Help Text
Error
```

### 17.2 Save

保存行为统一：

- 保存中 disabled；
- 成功有短暂反馈；
- 失败不清除表单；
- 有未保存修改时离开页面可提示（复杂设置页后续实现）。

### 17.3 Secret

密码/Token：

- 不回显；
- 已保存显示“已保存”；
- 修改必须明确触发；
- 测试连接不等于保存。

---

## 18. 确认对话框

危险操作必须使用统一 Confirm Dialog：

- 删除；
- 回退；
- 禁用关键对象；
- 取消正在运行的同步（若真正支持）；
- 批量拒绝；
- 破坏性配置切换。

禁止浏览器原生 `window.confirm` 与页面自制确认 UI 混用。

---

## 19. 颜色与 Token

优先复用现有 CSS Variables。

建议补充语义层：

```css
--admin-bg
--admin-surface
--admin-surface-muted
--admin-border
--admin-text
--admin-text-muted

--status-info
--status-info-bg
--status-success
--status-success-bg
--status-warning
--status-warning-bg
--status-danger
--status-danger-bg
```

颜色不直接散落为：

```css
#d33e4a
#d43d48
#de3b42
```

多个非常接近的红色。

整改目标是减少重复色值，而不是一次性重做整个 Token 系统。

---

## 20. Typography

建议：

- 页面标题：22–26px；
- Section Title：16–18px；
- Body：13–14px；
- Help/Meta：11–12px；
- Badge：10–11px；
- 表格正文：12–13px。

避免后台出现 39px 以上营销型标题。

---

## 21. Spacing

统一使用当前已有 spacing/token 体系。

推荐基础节奏：

```text
4 / 8 / 12 / 16 / 20 / 24 / 32
```

页面：

- desktop horizontal：28px 左右；
- mobile：16px；
- Panel gap：16–18px；
- Section 间距：18–24px。

---

## 22. Dark Mode

后台继续支持现有 `data-theme="dark"`。

要求：

- 状态颜色在 dark 下保持语义；
- Border 不消失；
- selected row 与 hover 可区分；
- input/select 背景不和 page bg 融在一起；
- 禁止只为 light theme 新增硬编码白色。

所有新 Admin 组件在 PR 内必须同时验证 light/dark。

---

## 23. 响应式断点

不新增大量断点。

继续围绕当前约：

- 900px；
- 760px。

### Desktop

- Sidebar 固定；
- 双栏 Workspace；
- Dashboard KPI 横向。

### Tablet

- Sidebar 可保留或压缩；
- Index detail 下移或缩窄；
- KPI 2x2。

### Mobile

- Sidebar Drawer；
- 页面单栏；
- Workspace detail 可变为 Drawer/下方区域；
- 表格横向滚动；
- 主操作保留可触达。

---

## 24. 可访问性

最低要求：

- 所有 icon-only button 有 `aria-label`；
- Active navigation 有可识别状态；
- Dialog focus trap；
- Escape 关闭非破坏性 Modal；
- 表单 Error 与 Field 关联；
- Toggle 有文本；
- Color 不作为唯一状态表达；
- Tree expand/collapse 有 `aria-expanded`；
- 动画遵守 `prefers-reduced-motion`；
- 键盘可完成主要后台工作流。

---

## 25. 后端契约约束

UI 整改必须尊重当前后端真实语义。

### 25.1 Index Progress

当前 AList Indexing 为全树扫描，无法可靠提前知道完整条目 total。

所以第一阶段：

- 不显示 fake percentage；
- 显示 root progress；
- 显示 current path；
- 显示 entries discovered；
- 显示 elapsed。

### 25.2 Sync State

UI 应依赖统一后端 Sync 状态，而不是：

- React mutation pending；
- 仅 manual task；
- 本地 timer。

后端整改后推荐返回：

```json
{
  "status": "running",
  "trigger": "manual|scheduler|startup",
  "cancellable": true,
  "roots_done": 2,
  "roots_total": 3,
  "current_path": "/Software",
  "entries_scanned": 83421,
  "elapsed_seconds": 161
}
```

不要求 UI PR 自己发起后端架构重写，但 UI 不能假设不存在的字段。

### 25.3 Stale Running

Indexing stale-running 恢复属于 UI 的前置可靠性依赖。

后台不能长期显示：

```text
正在同步
```

而实际上任务已随进程重启消失。

应先或并行解决后端恢复语义。

### 25.4 Full / Force

当前若后端 `full` / `force` 没有真实行为差异：

- UI 不暴露“完整同步 / 强制同步”模式；
- API 兼容字段可继续保留；
- 等后端具备真实语义再展示。

---

## 26. CSS 组织整改

### 26.1 当前问题

`apps/web/src/app/globals.css` 已承载大量：

- frontend；
- admin；
- catalog；
- notifications；
- hero animations；
- responsive；
- page-specific 样式。

继续增长会降低可维护性。

### 26.2 推荐目标

不需要引入 CSS-in-JS。

建议逐步拆为：

```text
apps/web/src/styles/
├── globals.css
├── admin-shell.css
├── admin-components.css
└── admin-pages.css
```

或继续与现有 Next 入口适配的等价结构。

### 26.3 拆分原则

仅在 UI 整改过程中搬动相关样式。

禁止单开一个巨型 PR：

> “整理全部 CSS”

因为会制造大量无产品价值 diff 和回归风险。

---

## 27. React 代码组织

推荐：

```text
components/admin/
features/admin/
app/admin/**
```

但保持克制。

页面状态仍可在 Page 中管理。

只有当出现真实跨页面复用时再下沉到：

```text
features/admin/
```

不要复制之前模块化阶段的过度抽象模式到前端。

---

## 28. 数据请求规范

继续使用 TanStack Query。

统一规则：

- queryKey 清晰；
- mutation success 精确 invalidate；
- 轮询仅对真实 running 状态开启；
- 后台页面切换不清空可复用缓存；
- refetch 失败时尽量保留最后成功数据；
- 不使用关键请求 `.catch(() => {})` 吞错。

---

## 29. 前端错误边界

关键页面至少处理：

- initial load error；
- partial block error；
- mutation error；
- session/auth error；
- 404 detail；
- stale selection；
- API schema 缺字段的安全 fallback。

不要所有异常都变成：

```text
不可用
```

必须在管理员可行动时提供下一步。

---

## 30. 开发阶段拆分

### P3c-0：UI 基线

目标：

- Admin Shell；
- 导航分组；
- AdminPageHeader；
- StatusBadge；
- Loading/Error/Empty；
- 统一 Toolbar；
- CSS Admin 区域初步拆分。

验收：

- 所有后台页面仍可访问；
- 不修改业务 API；
- light/dark 无明显回归；
- mobile 导航可用。

### P3c-1：Dashboard

目标：

- Dashboard 第一屏收口；
- 健康/同步/待处理/活动层级明确；
- 移除低价值重复卡片。

验收：

- 一屏可判断系统状态；
- 同步失败可见；
- 无数据时有明确 Empty；
- 页面轮询不闪烁。

### P3c-2：Index Workspace

目标：

- 管理员语言替代开发术语；
- Sync State Card；
- Tree + Detail 强化；
- 状态语义统一；
- 自动/手动状态对齐。

前置：

- stale-running 后端修复；
- sync state API 语义确认。

验收：

- 手动/自动/启动同步状态均能正确表达；
- 不显示 fake percentage；
- failed/partial/cancelled/skipped 可区分；
- 无 root 时正确引导。

### P3c-3：System Settings

目标：

- 从 Panel Stack 转为 Settings Template；
- 数据源 / root / sync 分区；
- Add/Edit Root 使用统一 Dialog/Drawer。

验收：

- 原有设置全部可操作；
- 修改配置不增加步骤；
- Secret 不泄露；
- 测试连接与保存语义清晰。

### P3c-4：Presentation

目标：

- 配置 + Preview 双栏；
- 主题/导航/区块变更可视化；
- Revision 回退统一。

验收：

- Preview 与 config 一致；
- mobile preview 可查看；
- 保存/发布状态明确；
- rollback 有确认。

### P3c-5：其余 Workspace

依次：

1. Automation；
2. Submissions；
3. Shares；
4. Users；
5. Notifications；
6. Catalog；
7. Collections；
8. Diagnostics。

优先按实际使用频率调整。

---

## 31. PR 策略

遵循 #157 已确定原则：

> 一条 PR 只收一个边界或一个明确 UI 主题。

推荐：

```text
PR A  Admin Shell + IA
PR B  Shared Admin UI States
PR C  Dashboard
PR D  Index Workspace
PR E  System Settings
PR F  Presentation Preview
...
```

禁止一个 PR 同时：

- 重做 Shell；
- 改 Index；
- 改 System；
- 搬全部 CSS；
- 顺手重构后端。

---

## 32. 代码修改重点文件

第一阶段预计涉及：

```text
apps/web/src/components/AdminShell.tsx
apps/web/src/components/admin/*
apps/web/src/app/globals.css
apps/web/src/app/admin/page.tsx
apps/web/src/app/admin/index/page.tsx
apps/web/src/app/admin/system/page.tsx
apps/web/src/app/admin/presentation/page.tsx
apps/web/src/lib/api.ts
```

后续页面按各自 PR 修改。

---

## 33. 测试策略

### 33.1 Unit / Component

重点：

- status mapping；
- nav active；
- format time；
- page header；
- empty/error；
- dialog behavior。

不要求为了每个静态 UI 写测试。

### 33.2 Existing Web Tests

继续保持现有：

`apps/web/tests/**`

不因重命名 class 大量破坏测试。

### 33.3 E2E

P3 UI 的最低 E2E：

#### Admin Shell

```text
login
→ /admin
→ sidebar navigation
→ index
→ system
→ logout
```

#### Index

```text
seed content
→ /admin/index
→ folder visible
→ select folder
→ detail visible
```

同步动作如果需要真实 AList，不在普通 seed E2E 伪造外部成功。

可以用明确 stub/fixture 测试 UI 状态，但测试名称必须说明是 UI contract fixture。

#### Presentation

```text
load config
→ change local setting
→ save
→ reload
→ setting persists
```

---

## 34. UI 验收矩阵

每个主要页面最低检查：

| 项目 | Desktop | Tablet | Mobile | Dark |
| --- | --- | --- | --- | --- |
| Loading | ✅ | ✅ | ✅ | ✅ |
| Empty | ✅ | ✅ | ✅ | ✅ |
| Error | ✅ | ✅ | ✅ | ✅ |
| Success | ✅ | ✅ | ✅ | ✅ |
| Long text | ✅ | ✅ | ✅ | ✅ |
| Action disabled | ✅ | ✅ | ✅ | ✅ |
| Keyboard | ✅ | - | ✅ | - |

---

## 35. 性能要求

后台不追求极端首屏指标，但需避免明显浪费：

- Tree 不重复 O(n²) 构造；
- 大列表分页；
- 不在每个 row 发独立 API；
- polling 仅 running；
- Search input debounce（需要远程请求时）；
- Detail query 只在选中后加载；
- 大 JSON 默认折叠；
- 不引入重型图表库只显示两个数字。

---

## 36. 安全要求

UI 整改不能弱化：

- Admin auth fail-closed；
- IDOR 后端检查；
- Secret 隐藏；
- Dangerous action confirm；
- 不把后端错误 stack 直接显示给普通管理员；
- 不在前端 LocalStorage 保存敏感 Token；
- 不因 UI Preview 绕过后端 publication 权限。

---

## 37. 文案规范

后台统一使用管理员语言。

推荐：

```text
内容同步
数据源
内容根目录
最近同步
已扫描
正在扫描
同步失败
部分完成
```

避免主界面直接使用：

```text
Indexing v2
FTS
reconcile
snapshot
provider adapter
ORM
outbox
```

这些可以出现在诊断/高级信息中。

---

## 38. 时间表达

管理员后台优先：

```text
刚刚
2 分钟前
今天 16:42
2026-09-19 16:42
```

关键审计记录应保留绝对时间。

不要只展示相对时间导致无法核对。

---

## 39. 高级信息

对技术管理员有价值但不适合作为主界面的信息，统一进入：

```text
高级信息 / 诊断详情
```

例如：

- engine_version；
- internal resource id；
- root_mapping_id；
- revision；
- raw error code；
- operation id；
- parser version。

---

## 40. 与 Indexing Runtime Hardening 的依赖

UI 整改与 Indexing 后端可靠性不是同一任务，但以下问题会直接影响 UI 正确性：

1. stale `v2_sync_progress.status=running` 在重启后必须恢复；
2. 自动/启动/手动同步的 running 状态需要统一；
3. cancellable 必须由后端真实声明；
4. partial / failed 语义需要稳定；
5. 不应让 UI 通过本地任务状态猜测服务端运行状态。

这些应作为 Index Workspace PR 的前置或并行工作。

---

## 41. 设计停止条件

后台 UI 不追求无限打磨。

某页面满足以下条件即停止：

- 信息层级清晰；
- 主任务 1–2 次点击可达；
- 状态真实；
- Error/Empty/Loading 完整；
- Desktop/Mobile 可用；
- Dark 可读；
- E2E 覆盖核心流程；
- 没有明显同类页面交互不一致；
- 再改只会增加装饰而不提升效率。

---

## 42. 最终目标

整改完成后，管理员进入 CloudSite 后台应形成稳定心智：

```text
概览
  看系统有没有问题

内容
  看资源从哪里来、如何组织、如何发布

运营
  管用户、分享、通知

运行
  查异常

站点
  控制前台长什么样

配置
  管底层连接和策略
```

而不是当前逐步形成的：

```text
“我记得这个功能好像在左边第 8 个页面。”
```

---

## 43. 执行优先级总表

| Priority | 工作 | 原因 |
| --- | --- | --- |
| P0 | Admin Shell / 导航 IA | 所有后台页面共享 |
| P0 | 通用状态语义 | 避免各页面继续分叉 |
| P0 | Index 状态真实性依赖 | 生产关键路径 |
| P1 | Dashboard | 后台入口体验 |
| P1 | Index Workspace | 内容核心 |
| P1 | System Settings | 配置复杂度正在上升 |
| P1 | Presentation Preview | 当前最缺视觉反馈 |
| P2 | Automation / Submissions | 高频工作台 |
| P2 | Shares / Users / Notifications | 运营一致性 |
| P2 | Catalog / Collections | 工作区收口 |
| P3 | Diagnostics 图形化 | 仅有真实统计数据后进行 |

---

## 44. 第一轮开发建议

建议第一轮只做：

```text
AdminShell
+ 导航分组
+ AdminPageHeader
+ AdminStatusBadge
+ AdminEmpty/Error/Loading
+ /admin Dashboard 收口
```

不要第一轮就进入所有业务页面。

第二轮：

```text
Index Runtime 状态修复
+ /admin/index Workspace
```

第三轮：

```text
/admin/system Settings
+ /admin/presentation Preview
```

完成这三轮后，再以它们作为标准模板批量收口其余后台页面。

---

## 45. Definition of Done

整个 UI 整改阶段完成的判断标准：

- [ ] 后台导航已按领域分组；
- [ ] Shell 在 desktop/mobile 可用；
- [ ] Dashboard 一屏能判断核心状态；
- [ ] Index 不暴露误导性 V2 技术主文案；
- [ ] Index 不伪造扫描百分比；
- [ ] 手动/自动/启动同步状态表现一致；
- [ ] System 使用 Settings Template；
- [ ] Presentation 有可视 Preview；
- [ ] 表格/Toolbar/Badge/Empty/Error/Loading 主要模式统一；
- [ ] dangerous actions 使用统一确认；
- [ ] light/dark 均通过人工验收；
- [ ] 核心后台导航和关键 Workspace 有可重复 E2E；
- [ ] globals.css 不再继续无边界堆积后台页面样式；
- [ ] 没有为了 UI 整改重新引入模块化架构债；
- [ ] Issue #157 P3c 可以进入“页面级产品优化”而不是继续修后台基础骨架。

---

## 46. 维护规则

后续新增后台页面时必须先选择：

- Dashboard；
- Workspace；
- Settings；

三类模板之一。

如果无法归类，先说明为什么现有模板不适用，再新增新模式。

新增 UI Pattern 至少满足一个条件：

1. 两个以上页面会复用；
2. 现有组件无法表达；
3. 能明显减少行为不一致。

不要因为“以后可能用”提前造组件。

---

## 47. 当前建议结论

CloudSite 后台现有 UI 基础约有 60–70% 可复用。

本次整改不需要推倒重来。

最有价值的工作是：

```text
导航 IA
→ 页面模板
→ 状态语义
→ Index Workspace
→ System Settings
→ Presentation Preview
→ 其余页面按模板收口
```

完成后，后台开发重心应从“继续搭 UI 骨架”转向具体产品体验、效率和异常处理。

