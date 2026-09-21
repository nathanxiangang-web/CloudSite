# CloudSite UI 静态快照 — 重新设计参考

> 本目录包含 CloudSite 所有前端页面的静态 HTML 快照，用于后续 UI 重新设计参考。
>
> 抓取时间：2026-09-21 14:24
> 来源：50号机 dev 实例 (http://192.168.178.50:3000)
> CSS 已内联，JS/图片资源指向 50号机绝对路径

---

## 页面分类总览

| 分类 | 文件数 | 说明 |
|------|--------|------|
| 公开页面 | 17 | 未登录即可访问的页面 |
| 用户页面 | 7 | 需要用户登录的账户相关页面 |
| 管理页面 | 18 | 管理员后台各功能页面 |
| 资源详情 | 5 | 实际资源/文件夹详情页示例 |
| **合计** | **47** | |

---

## 一、公开页面（17个）

未登录状态下即可访问的页面。部分页面在未登录时会重定向到登录页。

| 文件 | 路由 | 说明 | 备注 |
|------|------|------|------|
| `index.html` | `/` | 首页 | Hero区 + 分类网格 + 精选合集 + 最近更新 + 热门资源 |
| `browse.html` | `/browse` | 资源浏览页 | 类型筛选卡片 + 资源列表 |
| `browse-software.html` | `/browse?type=software` | 软件分类 | 当前选中"软件"类型 |
| `browse-image.html` | `/browse?type=image` | 图库分类 | 当前选中"图库"类型 |
| `browse-video.html` | `/browse?type=video` | 视频分类 | 当前选中"视频"类型 |
| `browse-document.html` | `/browse?type=document` | 教程分类 | 当前选中"教程"类型 |
| `browse-file.html` | `/browse?type=file` | 文件分类 | 当前选中"文件"类型 |
| `search.html` | `/search` | 搜索页 | 搜索输入 + 结果列表 |
| `login.html` | `/login` | 用户登录 | 用户名/密码登录表单 |
| `register.html` | `/register` | 用户注册 | 注册表单 |
| `about.html` | `/about` | 关于页 | 使用指南/平台介绍 |
| `terms.html` | `/terms` | 服务条款 | |
| `privacy.html` | `/privacy` | 隐私政策 | |
| `catalog.html` | `/catalog` | 目录页 | 资源目录索引 |
| `collections.html` | `/collections` | 精选合集 | 合集卡片网格 |
| `submit.html` | `/submit` | 投稿页 | 资源投稿表单 |
| `submissions.html` | `/submissions` | 投稿列表 | 我的投稿记录 |

### 已知问题
- 未登录时 `browse`/`search`/`catalog`/`collections` 等页面会重定向到登录页，快照内容为登录页
- 分类数量显示异常：所有245个资源被归为"文件"类型，"软件"/"图库"/"视频"/"教程"均为0（根因：root mapping配置变更后未重新索引）

---

## 二、用户页面（7个）

需要用户登录后才能访问的账户相关页面。已使用测试账号 (nathan) 登录后抓取。

| 文件 | 路由 | 说明 | 关键UI元素 |
|------|------|------|------------|
| `account.html` | `/account` | 账户中心 | 用户信息卡片 + 导航侧栏 |
| `account-favorites.html` | `/account/favorites` | 收藏夹 | 收藏资源列表 |
| `account-history.html` | `/account/history` | 浏览历史 | 最近浏览记录 |
| `account-security.html` | `/account/security` | 安全设置 | 密码修改 + 会话管理 |
| `account-shares.html` | `/account/shares` | 我的分享 | 分享链接列表 + 过期管理 |
| `account-follows.html` | `/account/follows` | 关注列表 | 关注的用户/合集 |
| `account-playback.html` | `/account/playback` | 播放记录 | 视频播放历史 |

---

## 三、管理页面（18个）

管理员后台页面。需管理员权限才能访问。

| 文件 | 路由 | 说明 | 关键UI元素 |
|------|------|------|------------|
| `admin.html` | `/admin` | 管理后台首页 | 概览面板 + 快捷入口 |
| `admin-login.html` | `/admin/login` | 管理员登录 | 管理员专用登录入口 |
| `admin-index.html` | `/admin/index` | 索引管理 | V2索引状态 + 同步控制 + 连接配置 |
| `admin-users.html` | `/admin/users` | 用户管理 | 用户列表 + 角色分配 + 状态控制 |
| `admin-system.html` | `/admin/system` | 系统设置 | 全局配置参数 |
| `admin-site.html` | `/admin/site` | 站点设置 | 站点名称/描述/主题/导航 |
| `admin-catalog.html` | `/admin/catalog` | 目录管理 | 目录分类配置 |
| `admin-catalog-entries.html` | `/admin/catalog/entries` | 目录条目 | 条目CRUD |
| `admin-collections.html` | `/admin/collections` | 合集管理 | 合集CRUD + 封面设置 |
| `admin-submissions.html` | `/admin/submissions` | 投稿审核 | 待审核投稿列表 + 批准/拒绝 |
| `admin-presentation.html` | `/admin/presentation` | 展示设置 | 主题预设 + 颜色/圆角/导航自定义 |
| `admin-diagnostics.html` | `/admin/diagnostics` | 诊断工具 | 系统健康检查 + 日志查看 |
| `admin-notifications.html` | `/admin/notifications` | 通知管理 | 通知模板 + 发送历史 |
| `admin-automation.html` | `/admin/automation` | 自动化 | 自动同步/索引规则配置 |
| `admin-shares.html` | `/admin/shares` | 分享管理 | 全站分享链接管理 |
| `admin-setup.html` | `/admin/setup` | 初始设置 | 首次部署配置 |
| `admin-setup-wizard.html` | `/admin/setup/wizard` | 设置向导 | 分步引导配置 |
| `admin-parser-candidates.html` | `/admin/parser-candidates` | 解析候选 | 文件解析规则管理 |

### 已知问题
- 大部分管理页面在非管理员账号下会重定向到 `admin-login`，快照内容为管理员登录页

---

## 四、资源详情页面（5个）

从浏览页中实际资源链接抓取的详情页示例。

| 文件 | 说明 |
|------|------|
| `detail-1.html` | 资源/文件夹详情页示例1 |
| `detail-2.html` | 资源/文件夹详情页示例2 |
| `detail-3.html` | 资源/文件夹详情页示例3 |
| `detail-4.html` | 资源/文件夹详情页示例4（内容最丰富） |
| `detail-5.html` | 资源/文件夹详情页示例5 |

### 关键UI元素
- 资源标题 + 元信息（大小/修改时间/类型）
- 下载/预览按钮
- 面包屑导航
- 文件列表（文件夹页面）
- 相关资源推荐

---

## 五、设计系统参考

### 色彩
- 主题色：`#2563eb`（蓝色 accent）
- 卡片圆角：`12px`
- 深色/浅色主题切换（`data-theme="light"`/`"dark"`）

### 布局
- 响应式卡片网格（分类筛选 2行×3列）
- 三列推荐条目布局
- 侧栏导航（账户/管理页面）

### 内容类型映射
| content_type | 中文标签 | 图标色 |
|--------------|----------|--------|
| software | 软件 | 蓝色 |
| image | 图库 | 绿色 |
| video | 视频 | 紫色 |
| document | 教程 | 橙色 |
| file | 文件 | 灰色 |

---

## 六、重新设计建议

### 优先级 P0
1. **分类浏览页** (`browse*.html`) — 修复分类数量显示，优化筛选交互
2. **首页** (`index.html`) — Hero区 + 分类入口 + 内容推荐
3. **资源详情页** (`detail-*.html`) — 信息层次 + 下载体验

### 优先级 P1
4. **搜索页** (`search.html`) — 搜索结果展示 + 过滤
5. **登录/注册** (`login.html`/`register.html`) — 表单设计
6. **账户中心** (`account*.html`) — 导航 + 信息卡片

### 优先级 P2
7. **管理后台** (`admin*.html`) — 数据表格 + 配置表单
8. **目录/合集** (`catalog.html`/`collections.html`) — 卡片设计
9. **静态页面** (`about.html`/`terms.html`/`privacy.html`) — 内容排版

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `*.html` | 47个页面静态快照（CSS已内联） |
| `readmeui.md` | 本文件 |
| `capture_ui.py` | 页面抓取脚本 |
| `inline_css.py` | CSS内联处理脚本 |