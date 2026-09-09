"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Boxes, Filter } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import {
  CATALOG_CONTENT_TYPE_LABELS,
  catalogEntryHref,
  contentTypeLabel,
} from "@/lib/catalog";
import { fetchCatalogEntries, fetchCatalogTags } from "@/lib/catalog-client";

const CONTENT_TYPES = ["software", "image", "video", "document", "file"];

export default function CatalogListPage() {
  const [contentType, setContentType] = useState<string>("");
  const [tag, setTag] = useState<string>("");
  const [page, setPage] = useState(1);

  const tags = useQuery({ queryKey: ["catalog-tags"], queryFn: fetchCatalogTags });
  const entries = useQuery({
    queryKey: ["catalog-entries", contentType, tag, page],
    queryFn: () => fetchCatalogEntries({ page, page_size: 24, content_type: contentType || undefined, tag: tag || undefined }),
  });

  const items = entries.data?.items ?? [];
  const total = entries.data?.total ?? 0;
  const totalPages = entries.data?.total_pages ?? 0;

  return <PublicShell><div className="page catalog-page">
    <section className="library-hero">
      <span className="library-folder type-document"><BookOpen /></span>
      <div>
        <h1>资源目录</h1>
        <p>按版本与平台整理的资源条目，每个条目可包含多个版本与下载位置。</p>
        <div className="meta">{total} 个已发布条目</div>
      </div>
    </section>

    <div className="catalog-toolbar">
      <div className="catalog-filter">
        <Filter size={15} />
        <select value={contentType} onChange={(event) => { setContentType(event.target.value); setPage(1); }} aria-label="按类型筛选">
          <option value="">全部类型</option>
          {CONTENT_TYPES.map((type) => <option key={type} value={type}>{CATALOG_CONTENT_TYPE_LABELS[type]}</option>)}
        </select>
      </div>
      {tags.data?.items.length ? <div className="catalog-filter">
        <select value={tag} onChange={(event) => { setTag(event.target.value); setPage(1); }} aria-label="按标签筛选">
          <option value="">全部标签</option>
          {tags.data.items.map((item) => <option key={item.tag_id} value={item.slug}>{item.display_name}</option>)}
        </select>
      </div> : null}
    </div>

    {entries.isLoading ? <div className="loading">正在加载目录…</div>
      : entries.error ? <div className="empty error-state">目录暂时不可用：{entries.error.message}</div>
      : items.length ? <section className="catalog-grid">{items.map((entry) => <Link key={entry.entry_id} href={catalogEntryHref(entry.entry_id)} className="catalog-card">
          <span className={`catalog-card-icon type-${entry.content_type}`}><Boxes /></span>
          <div className="catalog-card-body">
            <strong>{entry.title}</strong>
            <span className="catalog-card-summary">{entry.summary || "暂无简介"}</span>
            <div className="catalog-card-meta">
              <span className="catalog-card-type">{contentTypeLabel(entry.content_type)}</span>
              {entry.availability === "unavailable" && <span className="catalog-card-unavailable">暂不可用</span>}
              {entry.tags.slice(0, 3).map((tagItem) => <span key={tagItem.tag_id} className="catalog-card-tag">{tagItem.display_name}</span>)}
            </div>
          </div>
        </Link>)}</section>
      : <div className="empty">目录暂无已发布条目，管理员可在后台创建并发布目录条目。</div>}

    {totalPages > 1 && <nav className="pagination" aria-label="目录分页">
      <button type="button" disabled={page <= 1 || entries.isFetching} onClick={() => setPage((value) => value - 1)}>上一页</button>
      <span>第 {page} / {totalPages} 页</span>
      <button type="button" disabled={page >= totalPages || entries.isFetching} onClick={() => setPage((value) => value + 1)}>下一页</button>
    </nav>}
    <SiteFooter />
  </div></PublicShell>;
}
