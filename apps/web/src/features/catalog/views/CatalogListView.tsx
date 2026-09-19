"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Boxes, Filter, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";

import { fetchCatalogEntries, fetchCatalogSearch, fetchCatalogTags } from "../api";
import {
  CATALOG_CONTENT_TYPE_LABELS,
  catalogEntryHref,
  contentTypeLabel,
} from "../model";
import styles from "../styles/catalog-list.module.css";

const CONTENT_TYPES = ["software", "image", "video", "document", "file"];

function normalizeContentType(value: string | null): string {
  return value && CONTENT_TYPES.includes(value) ? value : "";
}

export function CatalogListView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const contentType = normalizeContentType(searchParams.get("type"));
  const tag = searchParams.get("tag") || "";
  const submittedQuery = (searchParams.get("q") || "").trim();
  const requestedPage = Number.parseInt(searchParams.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const [query, setQuery] = useState(submittedQuery);

  useEffect(() => {
    setQuery(submittedQuery);
  }, [submittedQuery]);

  const navigate = (next: { q?: string; contentType?: string; tag?: string; page?: number }) => {
    const values = new URLSearchParams();
    const nextQuery = (next.q ?? submittedQuery).trim();
    const nextContentType = normalizeContentType(next.contentType ?? contentType);
    const nextTag = next.tag ?? tag;
    const nextPage = next.page ?? page;
    if (nextQuery) values.set("q", nextQuery);
    if (nextContentType) values.set("type", nextContentType);
    if (nextTag) values.set("tag", nextTag);
    if (nextPage > 1) values.set("page", String(nextPage));
    router.push(`/catalog${values.size ? `?${values.toString()}` : ""}`);
  };

  const tags = useQuery({ queryKey: ["catalog-tags"], queryFn: fetchCatalogTags });
  const searchResults = useQuery({
    queryKey: ["catalog-search", submittedQuery, contentType, tag, page],
    queryFn: () => fetchCatalogSearch({
      q: submittedQuery,
      page,
      page_size: 24,
      content_type: contentType || undefined,
      tag: tag || undefined,
    }),
    enabled: Boolean(submittedQuery),
    placeholderData: (previous) => previous,
  });
  const entries = useQuery({
    queryKey: ["catalog-entries", contentType, tag, page],
    queryFn: () => fetchCatalogEntries({
      page,
      page_size: 24,
      content_type: contentType || undefined,
      tag: tag || undefined,
    }),
    enabled: !submittedQuery,
    placeholderData: (previous) => previous,
  });

  const searching = Boolean(submittedQuery);
  const items = searching ? (searchResults.data?.items ?? []) : (entries.data?.items ?? []);
  const total = searching ? (searchResults.data?.total ?? 0) : (entries.data?.total ?? 0);
  const totalPages = searching
    ? (searchResults.data?.total_pages ?? 0)
    : (entries.data?.total_pages ?? 0);
  const searchError = searching ? searchResults.error : entries.error;
  const isLoading = searching ? searchResults.isLoading : entries.isLoading;
  const isFetching = searching ? searchResults.isFetching : entries.isFetching;

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    navigate({ q: query, page: 1 });
  };

  return <PublicShell><div className={`page ${styles.page}`}>
    <section className="library-hero">
      <span className="library-folder type-document"><BookOpen /></span>
      <div>
        <h1>资源目录</h1>
        <p>按版本与平台整理的资源条目，每个条目可包含多个版本与下载位置。</p>
        <div className="meta">{total} 个已发布条目</div>
      </div>
    </section>

    <form className="catalog-search-form" onSubmit={submitSearch}>
      <Search />
      <input value={query} onChange={(event) => setQuery(event.target.value)}
        placeholder="搜索资源条目（标题、别名、标签、平台）" aria-label="搜索资源条目" />
      <button type="submit">搜索</button>
      {submittedQuery && <button type="button" onClick={() => { setQuery(""); navigate({ q: "", page: 1 }); }}>清除</button>}
    </form>

    <div className={styles.toolbar}>
      <div className={styles.filter}>
        <Filter size={15} />
        <select value={contentType} onChange={(event) => navigate({ contentType: event.target.value, page: 1 })} aria-label="按类型筛选">
          <option value="">全部类型</option>
          {CONTENT_TYPES.map((type) => <option key={type} value={type}>
            {CATALOG_CONTENT_TYPE_LABELS[type]}
          </option>)}
        </select>
      </div>
      {tags.data?.items.length ? <div className={styles.filter}>
        <select value={tag} onChange={(event) => navigate({ tag: event.target.value, page: 1 })} aria-label="按标签筛选">
          <option value="">全部标签</option>
          {tags.data.items.map((item) => <option key={item.tag_id} value={item.slug}>
            {item.display_name}
          </option>)}
        </select>
      </div> : null}
    </div>

    {isLoading ? <div className="loading">{searching ? "正在搜索条目…" : "正在加载目录…"}</div>
      : searchError ? <div className="empty error-state">
          {searching ? "搜索暂时不可用" : "目录暂时不可用"}：{searchError.message}
        </div>
      : items.length ? <section className={styles.grid}>{items.map((entry) =>
          <Link key={entry.entry_id} href={catalogEntryHref(entry.entry_id)} className={styles.card}>
            <span className={`${styles.icon} type-${entry.content_type}`}><Boxes /></span>
            <div className={styles.body}>
              <strong>{entry.title}</strong>
              <span className={styles.summary}>{entry.summary || "暂无简介"}</span>
              <div className={styles.meta}>
                <span className={styles.type}>{contentTypeLabel(entry.content_type)}</span>
                {entry.availability === "unavailable" &&
                  <span className={styles.unavailable}>暂不可用</span>}
                {entry.tags.slice(0, 3).map((tagItem) =>
                  <span key={tagItem.tag_id} className={styles.tag}>{tagItem.display_name}</span>)}
              </div>
            </div>
          </Link>)}</section>
      : searching ? <div className="empty"><strong>没有找到“{submittedQuery}”</strong>
          <span>{searchResults.data?.suggestion || "请尝试更换关键词或清除筛选条件。"}</span>
        </div>
      : <div className="empty">目录暂无已发布条目，管理员可在后台创建并发布目录条目。</div>}

    {totalPages > 1 && <nav className="pagination" aria-label="目录分页">
      <button type="button" disabled={page <= 1 || isFetching}
        onClick={() => navigate({ page: page - 1 })}>上一页</button>
      <span>第 {page} / {totalPages} 页</span>
      <button type="button" disabled={page >= totalPages || isFetching}
        onClick={() => navigate({ page: page + 1 })}>下一页</button>
    </nav>}
    <SiteFooter />
  </div></PublicShell>;
}
