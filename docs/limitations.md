# CloudSite 限制说明

> 1.0 稳定不等于隐瞒技术边界。以下限制在 1.0 中明确存在。

## Generic AList 不是 Delta

Generic AList Provider 使用 Rolling Full Verification，不提供真正的增量同步。只有明确声明 Delta 能力的 Provider 才进入 Delta Strategy。1.0 不宣传 Generic AList "真正增量"。

## 浏览器不支持所有视频编码

CloudSite 使用浏览器原生解码，不转码、不代理文件主体、不预生成 HLS。支持 MP4 H.264/AAC。不承诺所有 MKV/AVI/HEVC 格式。解码失败时提供下载降级。

## Folder ID 可能仍 Path-derived

Resource ID 从 0.3.0 起使用 Stable Resource ID（128-bit 随机 ID），可靠 Rename/Move 保持 ID 稳定。但 Folder ID 仍可能 Path-derived。不能模糊承诺"所有 URL 永久不变"。

## 302 无法完全隐藏 AList 最终地址

下载和二进制预览通过 HTTP 302 跳转到 AList 原生入口。浏览器地址栏可能显示 AList 的临时签名 URL。CloudSite 不代理文件主体，因此无法完全隐藏最终地址。

## CloudSite 不做代理下载 Body

下载、预览、分享下载均使用 302，CloudSite 不中转文件主体。这不是限制而是设计决策，避免 CloudSite 成为文件传输瓶颈。1.0 禁止改为 Body Proxy。

## Generic AList 无法 100% 识别所有 Move/Copy

Stable Resource ID 使用保守身份解析：同路径直接复用，可靠 Rename/Move 保留 ID，Copy 与 Path Reuse 生成新 ID。歧义场景宁可新 ID，不误合并。

## SQLite 并发限制

CloudSite 使用 SQLite（WAL 模式）。高并发写入时可能出现 `database is locked`。`busy_timeout=5000` 和 `wal_autocheckpoint=1000` 缓解此问题，但 SQLite 不适合极高并发场景。

## 不包含的功能

1.0 不包含以下功能（有需求在 1.1+）：

- Redis / PostgreSQL / Celery
- FFmpeg 转码 / HLS 切片
- 用户上传
- 付费 / 会员等级
- 评论社区
- 复杂 ACL
- AI 推荐
- 全文内容 OCR
- 大规模架构重写
