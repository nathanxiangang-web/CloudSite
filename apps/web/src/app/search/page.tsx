"use client";

import { useQuery } from "@tanstack/react-query";
import { File, Folder, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, ReactNode, Suspense, useEffect, useMemo, useState } from "react";
import { PublicShell } from "@/components/PublicShell";
import { api, formatBytes, SearchResponse, SearchResult } from "@/lib/api";
import { normalizeSearchQuery, SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";

type ContentRoots = { items: Array<{ content_type: string; display_name: string }> };

function SearchContent() {
  const router = useRouter();
  const params = useSearchParams();
  const query = normalizeSearchQuery(params.get("q") || "");
  const selectedType = params.get("type") || "";
  const sort = params.get("sort") || "relevance";
  const requestedPage = Number.parseInt(params.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const [input, setInput] = useState(query);
  useEffect(() => setInput(query), [query]);

  const roots = useQuery({ queryKey: ["content-roots"], queryFn: () => api<ContentRoots>("/api/content-roots") });
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

  const navigate = (next: { q?: string; type?: string; page?: number; sort?: string }) => {
    const values = new URLSearchParams();
    const nextQuery = normalizeSearchQuery(next.q ?? query);
    const nextType = next.type ?? selectedType;
    const nextPage = next.page ?? page;
    const nextSort = next.sort ?? sort;
    if (nextQuery) values.set("q", nextQuery);
    if (nextType) values.set("type", nextType);
    if (nextPage > 1) values.set("page", String(nextPage));
    if (nextSort !== "relevance") values.set("sort", nextSort);
    router.push(`/search${values.size ? `?${values.toString()}` : ""}`);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nextQuery = normalizeSearchQuery(input);
    if (nextQuery) navigate({ q: nextQuery, page: 1 });
  };

  return <PublicShell><div className="page search-page">
    <h1>搜索资源</h1>
    <p className="search-lead">从 CloudSite 索引中查找文件与文件夹，不会实时访问网盘。</p>
    <form onSubmit={submit}><Search /><input autoFocus maxLength={SEARCH_QUERY_MAX_LENGTH} value={input} onChange={(event) => setInput(event.target.value)} placeholder="搜索软件、图片、视频、文档和文件" /><button>搜索</button></form>

    {query ? <>
      <div className="search-toolbar">
        <div className="search-filters"><button className={!selectedType ? "active" : ""} onClick={() => navigate({ type: "", page: 1 })}>全部</button>{types.map((item) => <button className={selectedType === item.value ? "active" : ""} key={item.value} onClick={() => navigate({ type: item.value, page: 1 })}>{item.label}</button>)}</div>
        <label>排序<select value={sort} onChange={(event) => navigate({ sort: event.target.value, page: 1 })}><option value="relevance">相关度</option><option value="modified_at">最近更新</option><option value="name">名称</option><option value="size">文件大小</option></select></label>
      </div>
      <p className="result-summary">找到 {results.data?.total ?? 0} 个与“{query}”相关的结果{results.isFetching ? " · 正在更新…" : ""}</p>
      {results.isLoading ? <div className="loading search-state">正在搜索 CloudSite 索引…</div>
        : results.error ? <div className="empty error-state search-state"><strong>搜索暂时不可用</strong><span>{results.error.message}</span><button onClick={() => results.refetch()}>重试</button></div>
        : results.data?.items.length ? <section className="search-results">{results.data.items.map((item) => <SearchResultCard item={item} query={query} key={`${item.object_type}-${item.id}`} />)}</section>
        : <div className="empty search-state"><strong>没有找到“{query}”</strong><span>请尝试更换关键词或清除类型筛选。</span>{selectedType && <button onClick={() => navigate({ type: "", page: 1 })}>清除筛选</button>}</div>}
      {(results.data?.total_pages ?? 0) > 1 && <nav className="pagination"><button disabled={page <= 1} onClick={() => navigate({ page: page - 1 })}>上一页</button><span>第 {page} / {results.data?.total_pages} 页</span><button disabled={page >= (results.data?.total_pages ?? 0)} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav>}
    </> : <div className="empty search-state"><Search /><strong>开始搜索 CloudSite</strong><span>输入关键词，查找已同步的软件、图片、视频、文档、文件和目录。</span></div>}
  </div></PublicShell>;
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
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  if (!escaped) return text;
  return text.split(new RegExp(`(${escaped})`, "ig")).map((part, index) => part.localeCompare(query, undefined, { sensitivity: "accent" }) === 0 ? <mark key={index}>{part}</mark> : part);
}

export default function SearchPage() { return <Suspense><SearchContent /></Suspense>; }
