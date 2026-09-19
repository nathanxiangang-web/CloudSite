"use client";

import { useQuery } from "@tanstack/react-query";
import { Folder, Grid2X2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { FolderCard } from "@/components/FolderCard";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { api, ApiError, Folder as FolderType, Resource } from "@/lib/api";

type FolderDetail = {
  folder: FolderType;
  breadcrumbs: Array<{ id: string; name: string }>;
  child_folders: FolderType[];
  resources: { items: Resource[]; total: number; page: number; page_size: number; total_pages: number };
};

function normalizeSort(value: string | null): "modified_at" | "name" | "size" {
  return value === "modified_at" || value === "size" ? value : "name";
}

export default function FolderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const sort = normalizeSort(searchParams.get("sort"));
  const requestedPage = Number.parseInt(searchParams.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const order = sort === "name" ? "asc" : "desc";
  const navigate = (next: { page?: number; sort?: "modified_at" | "name" | "size" }) => {
    const values = new URLSearchParams();
    const nextPage = next.page ?? page;
    const nextSort = next.sort ?? sort;
    if (nextPage > 1) values.set("page", String(nextPage));
    if (nextSort !== "name") values.set("sort", nextSort);
    router.push(`/folder/${encodeURIComponent(id)}${values.size ? `?${values.toString()}` : ""}`);
  };
  const query = useQuery({ queryKey: ["folder", id, page, sort], queryFn: () => api<FolderDetail>(`/api/folders/${id}?page=${page}&page_size=24&sort=${sort}&order=${order}`), placeholderData: (previous) => previous });
  const data = query.data;
  if (query.isLoading) return <PublicShell><div className="page loading">正在加载文件夹索引…</div></PublicShell>;
  if (query.error) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return <PublicShell><div className={`page state-page${notFound ? "" : " error-state"}`}><strong>{notFound ? "404" : "加载失败"}</strong><h1>{notFound ? "文件夹不可用" : "文件夹暂时无法加载"}</h1><p>{query.error.message}</p>{notFound ? <Link href="/">返回首页</Link> : <button type="button" onClick={() => query.refetch()}>重试</button>}</div></PublicShell>;
  }
  if (!data) return null;
  return <PublicShell><div className="page library-page"><nav className="breadcrumb"><Link href="/">资源库</Link>{data.breadcrumbs.map((item) => <span key={item.id}>› <Link href={`/folder/${item.id}`}>{item.name}</Link></span>)}</nav><section className="library-hero"><span className={`library-folder type-${data.folder.content_type}`}><Folder /></span><div><h1>{data.folder.name}</h1><p>通过安全目录 ID 浏览，底层网盘路径不会公开。</p><div className="meta">{data.child_folders.length} 个子文件夹 · {data.resources.total} 个资源</div></div></section>{data.child_folders.length > 0 && <><h2 className="subheading">子文件夹</h2><section className="folder-grid">{data.child_folders.map((folder) => <FolderCard item={folder} key={folder.id} />)}</section></>}<div className="library-toolbar"><h2>资源</h2><div><label className="library-sort">排序<select value={sort} onChange={(event) => navigate({ sort: normalizeSort(event.target.value), page: 1 })}><option value="name">名称</option><option value="modified_at">最近更新</option><option value="size">文件大小</option></select></label><button className="selected" aria-label="网格视图"><Grid2X2 /></button></div></div><section className="resource-grid">{data.resources.items.length ? data.resources.items.map((resource) => <ResourceCard item={resource} key={resource.id} />) : <div className="empty">此文件夹暂时没有资源。</div>}</section>{data.resources.total_pages > 1 && <nav className="pagination"><button type="button" disabled={page <= 1 || query.isFetching} onClick={() => navigate({ page: page - 1 })}>上一页</button><span>第 {page} / {data.resources.total_pages} 页</span><button type="button" disabled={page >= data.resources.total_pages || query.isFetching} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav>}</div></PublicShell>;
}
