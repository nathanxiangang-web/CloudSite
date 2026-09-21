"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Boxes, Filter, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent } from "react";

import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { LibraryTabs, redesignStyles } from "@/features/public-redesign";

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
  const countText = searchError ? "条目数量不可用" : isLoading ? "正在读取条目…" : `${total} 个已发布条目`;

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    navigate({ q: String(form.get("q") || ""), page: 1 });
  };

  return <PublicShell><div className={`page ${styles.page} ${redesignStyles.libraryPage}`}>
    <div className={redesignStyles.libraryBreadcrumb}>资源库 <span>›</span> 资源条目</div>
    <section className={redesignStyles.libraryIntro}>
      <span className={redesignStyles.libraryIntroIcon}><BookOpen /></span>
      <div>
        <h1>资源条目</h1>
        <p>经过整理的内容条目，可包含说明、标签、多个版本以及对应的下载文件。</p>
      </div>
      <div className={redesignStyles.libraryIntroMeta}>
        <span className={redesignStyles.metricChip}>{countText}</span>
      </div>
    </section>
    <LibraryTabs active="catalog" />

    <form className={`catalog-search-form ${redesignStyles.searchForm}`} onSubmit={submitSearch}>
      <Search />
      <input key={submittedQuery} name="q" defaultValue={submittedQuery}
        placeholder="搜索资源条目（标题、别名、标签、平台）" aria-label="搜索资源条目" />
      <button type="submit">搜索</button>
      {submittedQuery && <button type="button" onClick={() => navigate({ q: "", page: 1 })}>清除</button>}
    </form>

    <div className={redesignStyles.catalogToolbar}>
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
    {tags.error && <div className="empty error-state">标签筛选暂时不可用：{tags.error.message}<button type="button" onClick={() => tags.refetch()}>重试</button></div>}

    {isLoading ? <div className="loading">{searching ? "正在搜索条目…" : "正在加载目录…"}</div>
      : searchError ? <div className="empty error-state">
          {searching ? "搜索暂时不可用" : "目录暂时不可用"}：{searchError.message}
          <button type="button" onClick={() => searching ? searchResults.refetch() : entries.refetch()}>重试</button>
        </div>
      : items.length ? <section className={redesignStyles.catalogGrid}>{items.map((entry) =>
          <Link key={entry.entry_id} href={catalogEntryHref(entry.entry_id)} className={redesignStyles.catalogCard}>
            <span className={`${redesignStyles.catalogCardIcon} type-${entry.content_type}`}><Boxes /></span>
            <div className={redesignStyles.catalogCardBody}>
              <strong>{entry.title}</strong>
              <span className={redesignStyles.catalogCardSummary}>{entry.summary || "暂无简介"}</span>
              <div className={redesignStyles.catalogCardMeta}>
                <span className={redesignStyles.catalogPill}>{contentTypeLabel(entry.content_type)}</span>
                <span className={entry.availability === "available" ? redesignStyles.availablePill : redesignStyles.unavailablePill}>
                  {entry.availability === "available" ? "可用" : "暂不可用"}
                </span>
                {entry.tags.slice(0, 3).map((tagItem) =>
                  <span key={tagItem.tag_id} className={redesignStyles.catalogPill}>{tagItem.display_name}</span>)}
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
