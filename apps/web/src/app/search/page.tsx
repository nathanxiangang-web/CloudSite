"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, ReactNode, Suspense, useEffect, useMemo, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { api, formatBytes, SearchResponse, SearchResult } from "@/lib/api";
import { Boxes, File, Folder, Search } from "lucide-react";
import { normalizeSearchQuery, SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";
import { catalogEntryHref, contentTypeLabel, type CatalogSearchItem, type CatalogSearchResponse } from "@/lib/catalog";
import { fetchCatalogSearch } from "@/lib/catalog-client";

type ContentRoots = { items: Array<{ content_type: string; display_name: string }> };

const HISTORY_KEY = "cloudsite-search-history";
const HISTORY_MAX = 8;

function loadHistory(): string[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]"); } catch { return []; }
}

function SearchContent() {
  const router = useRouter();
  const params = useSearchParams();
  const query = normalizeSearchQuery(params.get("q") || "");
  const selectedType = params.get("type") || "";
  const sort = params.get("sort") || "relevance";
  const requestedPage = Number.parseInt(params.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const requestedCatalogPage = Number.parseInt(params.get("catalog_page") || "1", 10);
  const catalogPage = Number.isFinite(requestedCatalogPage) && requestedCatalogPage > 0 ? requestedCatalogPage : 1;
  const [input, setInput] = useState(query);
  const [syncedQuery, setSyncedQuery] = useState(query);
  if (query !== syncedQuery) {
    setSyncedQuery(query);
    setInput(query);
  }
  const [history, setHistory] = useState<string[]>(() => loadHistory());
  const [recordedQuery, setRecordedQuery] = useState<string | null>(null);

  const roots = useQuery({ queryKey: ["content-roots"], queryFn: () => api<ContentRoots>("/api/content-roots"), staleTime: 5 * 60 * 1000 });
  const types = useMemo(() => {
    const unique = new Map<string, string>();
    roots.data?.items.forEach((item) => unique.set(item.content_type, item.display_name));
    return [...unique.entries()].map(([value, label]) => ({ value, label }));
  }, [roots.data]);
  const requestPath = `/api/search?q=${encodeURIComponent(query)}&page=${page}&page_size=24&sort=${encodeURIComponent(sort)}${selectedType ? `&type=${encodeURIComponent(selectedType)}` : ""}`;
  const results = useQuery({
    queryKey: ["search", query, selectedType, page, sort],
    queryFn: () => api<SearchResponse>(requestPath),
    enabled: Boolean(query),
    placeholderData: (previous) => previous,
  });

  const catalogResults = useQuery({
    queryKey: ["catalog-search", query, selectedType, catalogPage],
    queryFn: () => fetchCatalogSearch({ q: query, page: catalogPage, page_size: 24, content_type: selectedType || undefined }),
    enabled: Boolean(query),
    placeholderData: (previous) => previous,
  });

  // 搜索成功后记录历史
  const pendingRecord = query && (results.data?.items.length || catalogResults.data?.items.length) ? query : null;
  if (pendingRecord && pendingRecord !== recordedQuery) {
    setRecordedQuery(pendingRecord);
    setHistory([pendingRecord, ...history.filter((h) => h !== pendingRecord)].slice(0, HISTORY_MAX));
  }
  useEffect(() => {
    if (!recordedQuery) return;
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(history)); } catch {}
  }, [recordedQuery, history]);

  const navigate = (next: { q?: string; type?: string; page?: number; catalogPage?: number; sort?: string }) => {
    const values = new URLSearchParams();
    const nextQuery = normalizeSearchQuery(next.q ?? query);
    const nextType = next.type ?? selectedType;
    const nextPage = next.page ?? page;
    const nextCatalogPage = next.catalogPage ?? catalogPage;
    const nextSort = next.sort ?? sort;
    if (nextQuery) values.set("q", nextQuery);
    if (nextType) values.set("type", nextType);
    if (nextPage > 1) values.set("page", String(nextPage));
    if (nextCatalogPage > 1) values.set("catalog_page", String(nextCatalogPage));
    if (nextSort !== "relevance") values.set("sort", nextSort);
    router.push(`/search${values.size ? `?${values.toString()}` : ""}`);
  };

  // debounce 300ms 自动搜索
  useEffect(() => {
    const normalized = normalizeSearchQuery(input);
    if (!normalized || normalized === query) return;
    const timer = setTimeout(() => {
      const values = new URLSearchParams();
      values.set("q", normalized);
      if (selectedType) values.set("type", selectedType);
      if (sort !== "relevance") values.set("sort", sort);
      router.push(`/search?${values.toString()}`);
    }, 300);
    return () => clearTimeout(timer);
  }, [input, query, selectedType, sort, router]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nextQuery = normalizeSearchQuery(input);
    if (nextQuery) navigate({ q: nextQuery, page: 1, catalogPage: 1 });
  };

  return <PublicShell><div className="page search-page">
    <h1>搜索资源</h1>
    <p className="search-lead">从 CloudSite 索引中查找文件与文件夹，不会实时访问网盘。</p>
    <form onSubmit={submit}><Search /><input autoFocus maxLength={SEARCH_QUERY_MAX_LENGTH} value={input} onChange={(event) => setInput(event.target.value)} placeholder="搜索软件、图库、视频、教程和文件" /><button>搜索</button></form>

    {query ? <>
      <div className="search-toolbar">
        <div className="search-filters"><button className={!selectedType ? "active" : ""} onClick={() => navigate({ type: "", page: 1, catalogPage: 1 })}>全部</button>{types.map((item) => <button className={selectedType === item.value ? "active" : ""} key={item.value} onClick={() => navigate({ type: item.value, page: 1, catalogPage: 1 })}>{item.label}</button>)}</div>
        <label>文件结果排序<select value={sort} onChange={(event) => navigate({ sort: event.target.value, page: 1 })}><option value="relevance">相关度</option><option value="modified_at">最近更新</option><option value="name">名称</option><option value="size">文件大小</option></select></label>
      </div>
      <p className="result-summary">找到 {results.data?.total ?? 0} 个文件结果与 {catalogResults.data?.total ?? 0} 个资源条目{results.isFetching || catalogResults.isFetching ? " · 正在更新…" : ""}</p>
      {catalogResults.error && <div className="empty error-state search-state"><strong>资源条目搜索暂时不可用</strong><span>{catalogResults.error.message}</span><button type="button" onClick={() => catalogResults.refetch()}>重试</button></div>}
      {catalogResults.data && catalogResults.data.total > 0 && <section className="search-results catalog-results-section" aria-label="资源条目结果">
        <h2 className="search-section-title">资源条目</h2>
        {catalogResults.data.items.map((item) => <CatalogSearchCard item={item} query={query} key={`catalog-${item.entry_id}`} />)}
        {(catalogResults.data.total_pages ?? 0) > 1 && <nav className="pagination" aria-label="资源条目分页"><button disabled={catalogPage <= 1 || catalogResults.isFetching} onClick={() => navigate({ catalogPage: catalogPage - 1 })}>上一页</button><span>第 {catalogResults.data.page} / {catalogResults.data.total_pages} 页 · 共 {catalogResults.data.total} 个条目</span><button disabled={catalogPage >= catalogResults.data.total_pages || catalogResults.isFetching} onClick={() => navigate({ catalogPage: catalogPage + 1 })}>下一页</button></nav>}
      </section>}
      {results.isLoading ? <div className="loading search-state">正在搜索 CloudSite 索引…</div>
        : results.error ? <div className="empty error-state search-state"><strong>搜索暂时不可用</strong><span>{results.error.message}</span><button onClick={() => results.refetch()}>重试</button></div>
        : results.data?.items.length ? <section className="search-results">{results.data.items.map((item) => <SearchResultCard item={item} query={query} key={`${item.object_type}-${item.id}`} />)}</section>
        : (results.data?.total === 0 && catalogResults.data?.total === 0) ? <div className="empty search-state"><strong>没有找到“{query}”</strong><span>{catalogResults.data?.suggestion || "请尝试更换关键词或清除类型筛选。"}</span>{selectedType && <button onClick={() => navigate({ type: "", page: 1, catalogPage: 1 })}>清除筛选</button>}</div> : null}
      {(results.data?.total_pages ?? 0) > 1 && <nav className="pagination"><button disabled={page <= 1 || results.isFetching} onClick={() => navigate({ page: page - 1 })}>上一页</button><span>第 {page} / {results.data?.total_pages} 页</span><button disabled={page >= (results.data?.total_pages ?? 0) || results.isFetching} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav>}
    </> : <div className="empty search-state"><Search /><strong>开始搜索 CloudSite</strong><span>输入关键词，查找已公开的软件、图库、视频、教程、文件和目录。</span>
      {history.length > 0 && <div className="search-history" style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
        <small style={{ width: "100%", color: "var(--muted)", fontSize: 11 }}>最近搜索</small>
        {history.map((h) => <button key={h} onClick={() => navigate({ q: h, page: 1, catalogPage: 1 })} style={{ minHeight: 32, padding: "0 12px", borderRadius: 999, fontSize: 12, border: "1px solid var(--line)", background: "#fff", color: "#46546c" }}>{h}</button>)}
      </div>}
    </div>}
  </div></PublicShell>;
}

function CatalogSearchCard({ item, query }: { item: CatalogSearchItem; query: string }) {
  return <Link href={catalogEntryHref(item.entry_id)} className="search-result-card catalog-result-card">
    <span className={`search-result-icon type-${item.content_type}`}><Boxes /></span>
    <span className="search-result-copy"><strong><Highlight text={item.title} query={query} /></strong><small>{item.summary || "暂无简介"} · 资源条目</small></span>
    <span className="search-result-meta">{contentTypeLabel(item.content_type)}{item.tags.slice(0, 2).length ? ` · ${item.tags.slice(0, 2).map((tag) => tag.display_name).join(" / ")}` : ""}</span>
  </Link>;
}

function SearchResultCard({ item, query }: { item: SearchResult; query: string }) {
  const href = item.object_type === "folder" ? `/folder/${item.id}` : `/resource/${item.id}`;
  const Icon = item.object_type === "folder" ? Folder : File;
  const breadcrumb = item.breadcrumbs.map((entry) => entry.name).join(" / ");
  return <Link href={href} className="search-result-card">
    <span className={`search-result-icon type-${item.content_type}`}><Icon /></span>
    <span className="search-result-copy"><strong><Highlight text={item.name} query={query} /></strong><small>{breadcrumb || (item.object_type === "folder" ? "根目录" : item.parent?.name || "CloudSite")}</small></span>
    <span className="search-result-meta">{item.object_type === "folder" ? `${item.child_folder_count} 个子目录 · ${item.resource_count} 个资源` : `${item.extension?.toUpperCase() || "文件"} · ${formatBytes(item.size || 0)}`}</span>
  </Link>;
}

function Highlight({ text, query }: { text: string; query: string }): ReactNode {
  const regex = useMemo(() => {
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return escaped ? new RegExp(`(${escaped})`, "ig") : null;
  }, [query]);
  if (!regex) return text;
  return text.split(regex).map((part, index) => part.localeCompare(query, undefined, { sensitivity: "accent" }) === 0 ? <mark key={index}>{part}</mark> : part);
}

export default function SearchPage() { return <Suspense><SearchContent /></Suspense>; }
