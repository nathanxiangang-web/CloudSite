"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes, FileText, Plus, Tag } from "lucide-react";
import Link from "next/link";
import { AdminShell } from "@/components/AdminShell";
import {
  catalogEntryHref,
  contentTypeLabel,
  statusLabel,
} from "@/lib/catalog";
import { fetchAdminCatalogEntries } from "@/lib/catalog-client";

export default function AdminCatalogOverview() {
  const entries = useQuery({ queryKey: ["admin-catalog-entries"], queryFn: () => fetchAdminCatalogEntries() });
  const items = entries.data?.items ?? [];

  return <AdminShell title="目录管理"><div className="admin-page">
    <section className="panel collection-create">
      <div><h2><Boxes />目录管理</h2><p className="panel-intro">目录条目是面向用户的资源视图，可绑定已索引文件作为下载位置并发布。</p></div>
      <div className="card-actions">
        <Link className="button primary" href="/admin/catalog/entries"><Plus />新建条目</Link>
        <Link className="button" href="/admin/catalog/entries">管理全部条目</Link>
      </div>
    </section>

    {entries.isLoading ? <div className="loading">正在加载目录条目…</div>
      : entries.error ? <div className="empty error-state">加载失败：{entries.error.message}<button type="button" onClick={() => entries.refetch()}>重试</button></div>
      : items.length ? <section className="collection-admin-grid">{items.map((entry) => <article className="panel collection-admin-card" key={entry.entry_id}>
        <div className="collection-admin-head">
          <span className="stat-icon purple"><Boxes /></span>
          <div><h2>{entry.title}</h2><p>{entry.summary || "暂无简介"}</p></div>
        </div>
        <dl>
          <div><dt>类型</dt><dd>{contentTypeLabel(entry.content_type)}</dd></div>
          <div><dt>状态</dt><dd>{statusLabel(entry.status)}</dd></div>
          <div><dt>可用性</dt><dd>{entry.availability === "available" ? "可用" : "不可用"}</dd></div>
          <div><dt>版本数</dt><dd>{entry.releases.length}</dd></div>
        </dl>
        <div className="card-actions">
          <Link className="button" href={`/admin/catalog/entries/${entry.entry_id}`}>编辑</Link>
          <Link className="button" href={catalogEntryHref(entry.entry_id)}>预览</Link>
        </div>
      </article>)}</section>
      : <div className="panel empty"><FileText />还没有目录条目，先创建一个。</div>}

    <section className="panel"><h2><Tag />说明</h2><p className="panel-intro">目录条目通过绑定已索引文件作为下载位置，发布后对认证用户可见。底层文件浏览、预览与下载入口保持不变。</p></section>
  </div></AdminShell>;
}
