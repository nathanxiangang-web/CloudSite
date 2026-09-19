"use client";

import { useQuery } from "@tanstack/react-query";
import { Grid2X2, PanelsTopLeft, Image, Clapperboard, FileText, File } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { GalleryCard } from "@/components/GalleryCard";
import { api, Resource } from "@/lib/api";

const typeMeta = {
  software: { label: "软件", icon: PanelsTopLeft },
  image: { label: "图库", icon: Image },
  video: { label: "视频", icon: Clapperboard },
  document: { label: "教程", icon: FileText },
  file: { label: "文件", icon: File },
} as const;

type BrowsePage = {
  type: string | null;
  type_entries: { type: string; display_name: string; count: number; url: string }[];
  counts: Record<string, number>;
  items: Resource[];
  total: number;
  page: number;
  page_size: number;
  sort: "modified_at" | "name" | "size";
  order: "asc" | "desc";
  total_pages: number;
  catalog_entries: { entry_id: string; title: string; summary: string; content_type: string; slug: string; cover_resource_id: string | null; featured: boolean }[];
};

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function normalizeSort(value: string | null): "modified_at" | "name" {
  return value === "name" ? "name" : "modified_at";
}

export default function BrowsePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeType = searchParams.get("type") || "";
  const sort = normalizeSort(searchParams.get("sort"));
  const requestedPage = Number.parseInt(searchParams.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const order = sort === "name" ? "asc" : "desc";

  const navigate = (next: { type?: string; sort?: "modified_at" | "name"; page?: number }) => {
    const values = new URLSearchParams();
    const nextType = next.type ?? activeType;
    const nextSort = next.sort ?? sort;
    const nextPage = next.page ?? page;
    if (nextType) values.set("type", nextType);
    if (nextSort !== "modified_at") values.set("sort", nextSort);
    if (nextPage > 1) values.set("page", String(nextPage));
    router.push(`/browse${values.size ? `?${values.toString()}` : ""}`);
  };

  const browseHref = (type: string) => {
    const values = new URLSearchParams();
    if (type) values.set("type", type);
    if (sort !== "modified_at") values.set("sort", sort);
    return `/browse${values.size ? `?${values.toString()}` : ""}`;
  };

  const request = new URLSearchParams({
    page: String(page),
    page_size: "24",
    sort,
    order,
  });
  if (activeType) request.set("type", activeType);

  const browse = useQuery({
    queryKey: ["browse", activeType, page, sort],
    queryFn: () => api<BrowsePage>(`/api/browse?${request.toString()}`),
    placeholderData: (previous) => previous,
  });

  const data = browse.data;
  const label = activeType && activeType in typeMeta ? typeMeta[activeType as keyof typeof typeMeta].label : "全类型";
  const total = data?.total ?? 0;

  return <PublicShell><div className="page library-page"><div className="breadcrumb">资源库 <span>›</span> {label}</div>
    <section className="library-hero"><span className="library-folder type-file"><Grid2X2 /></span><div><h1>{label}浏览</h1><p>浏览所有类型的资源，支持按类型筛选。页面不会实时读取或暴露底层网盘路径。</p><div className="meta">{total} 个资源</div></div></section>

    <div className="library-toolbar"><h2>类型筛选</h2></div>
    <section className="category-grid">
      <Link href={browseHref("")} className={`category-card${!activeType ? " active" : ""}`}><span className="category-icon type-file"><Grid2X2 /></span><span><strong>全类型</strong><small>{formatCount(Object.values(data?.counts ?? {}).reduce((a, b) => a + b, 0))} 个资源</small></span></Link>
      {(data?.type_entries ?? []).map((entry) => {
        const meta = entry.type in typeMeta ? typeMeta[entry.type as keyof typeof typeMeta] : typeMeta.file;
        const Icon = meta.icon;
        return <Link href={browseHref(entry.type)} className={`category-card${activeType === entry.type ? " active" : ""}`} key={entry.type}><span className={`category-icon type-${entry.type}`}><Icon /></span><span><strong>{entry.display_name}</strong><small>{formatCount(entry.count)} 个资源</small></span></Link>;
      })}
    </section>

    {data && data.catalog_entries.length > 0 && <><h2 className="subheading">推荐条目</h2><section className="resource-grid">{data.catalog_entries.map((entry) => <Link href={`/catalog/${entry.slug}`} className="popular-card" key={entry.entry_id}><strong title={entry.title}>{entry.title}</strong><small>{entry.summary}</small>{entry.featured && <span className="type-pill type-software">精选</span>}</Link>)}</section></>}

    <div className="library-toolbar"><h2>全部资源</h2><div><label className="library-sort">排序<select value={sort} onChange={(event) => navigate({ sort: normalizeSort(event.target.value), page: 1 })}><option value="modified_at">最近更新</option><option value="name">名称</option></select></label><button className="selected" aria-label="网格视图"><Grid2X2 /></button></div></div>
    <section className={activeType === "image" ? "gallery-grid" : "resource-grid"}>{browse.isLoading ? <div className="loading">正在加载资源索引…</div> : browse.error ? <div className="empty error-state">加载失败：{browse.error.message}</div> : data && data.items.length ? data.items.map((item) => activeType === "image" ? <GalleryCard key={item.id} item={item} /> : <ResourceCard key={item.id} item={item} />) : <div className="empty">当前筛选条件下暂无资源。完成 AList 配置和同步后会自动显示。</div>}</section>
    {(data?.total_pages ?? 0) > 1 && <nav className="pagination" aria-label="资源分页"><button type="button" disabled={page <= 1 || browse.isFetching} onClick={() => navigate({ page: page - 1 })}>上一页</button><span>第 {page} / {data?.total_pages} 页</span><button type="button" disabled={page >= (data?.total_pages ?? 1) || browse.isFetching} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav>}
  </div></PublicShell>;
}
