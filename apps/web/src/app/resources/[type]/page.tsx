"use client";

import { useQuery } from "@tanstack/react-query";
import { Folder, Grid2X2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { FolderCard } from "@/components/FolderCard";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { GalleryCard } from "@/components/GalleryCard";
import { LibraryTabs, redesignStyles } from "@/features/public-redesign";
import { api, Folder as FolderType, Resource } from "@/lib/api";

const labels: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "全部文件" };
type ResourcePage = { items: Resource[]; total: number; page: number; page_size: number; total_pages: number };

function normalizeSort(value: string | null): "modified_at" | "name" | "size" {
  return value === "name" || value === "size" ? value : "modified_at";
}

export default function ResourceLibrary() {
  const { type } = useParams<{ type: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const sort = normalizeSort(searchParams.get("sort"));
  const requestedPage = Number.parseInt(searchParams.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const navigate = (next: { page?: number; sort?: "modified_at" | "name" | "size" }) => {
    const values = new URLSearchParams();
    const nextPage = next.page ?? page;
    const nextSort = next.sort ?? sort;
    if (nextPage > 1) values.set("page", String(nextPage));
    if (nextSort !== "modified_at") values.set("sort", nextSort);
    router.push(`/resources/${encodeURIComponent(type)}${values.size ? `?${values.toString()}` : ""}`);
  };
  const label = labels[type] || "资源";
  const resources = useQuery({ queryKey: ["resources", type, page, sort], queryFn: () => api<ResourcePage>(`/api/resources?type=${encodeURIComponent(type)}&page=${page}&page_size=24&sort=${sort}&order=${sort === "name" ? "asc" : "desc"}`), placeholderData: (previous) => previous });
  const folders = useQuery({ queryKey: ["folders", type], queryFn: () => api<{ items: FolderType[] }>(`/api/folders?content_type=${encodeURIComponent(type)}`) });
  const roots = folders.data?.items.filter((folder) => folder.depth <= 1).slice(0, 8) ?? [];
  const resourceCount = resources.data ? `${resources.data.total} 个资源` : resources.isLoading ? "资源读取中" : "资源数量不可用";
  const folderCount = folders.data ? `${folders.data.items.length} 个文件夹` : folders.isLoading ? "文件夹读取中" : "文件夹数量不可用";
  return <PublicShell><div className={`page library-page ${redesignStyles.libraryPage}`}>
    <div className={redesignStyles.libraryBreadcrumb}>资源库 <span>›</span> 文件与目录 <span>›</span> {label}</div>
    <section className={redesignStyles.libraryIntro}>
      <span className={redesignStyles.libraryIntroIcon}><Folder /></span>
      <div>
        <h1>{label} · 文件与目录</h1>
        <p>浏览 CloudSite 已完成索引的文件与目录；真实网盘路径、连接地址和凭据不会暴露给普通用户。</p>
      </div>
      <div className={redesignStyles.libraryIntroMeta}>
        <span className={redesignStyles.metricChip}>{resourceCount}</span>
        <span className={redesignStyles.metricChip}>{folderCount}</span>
      </div>
    </section>
    <LibraryTabs active="files" contentType={type} />
    {folders.error ? <div className="empty error-state">文件夹加载失败：{folders.error.message}<button type="button" onClick={() => folders.refetch()}>重试</button></div> : roots.length > 0 && <>
      <div className={redesignStyles.sectionHeader}><div><h2>可进入的文件夹</h2><p>进入文件夹继续浏览索引层级</p></div></div>
      <section className={redesignStyles.folderGrid}>{roots.map((folder) => <FolderCard item={folder} key={folder.id} />)}</section>
    </>}
    <div className={redesignStyles.sectionHeader}>
      <div><h2>文件结果</h2><p>{type === "image" ? "图片使用缩略图网格" : "其余类型使用便于快速扫描的列表"}</p></div>
      <div><label className="library-sort">文件结果排序<select value={sort} onChange={(event) => navigate({ sort: normalizeSort(event.target.value), page: 1 })}><option value="modified_at">最近更新</option><option value="name">名称</option><option value="size">文件大小</option></select></label><button className="selected" aria-label={type === "image" ? "缩略图视图" : "列表视图"}><Grid2X2 /></button></div>
    </div>
    <section className={type === "image" ? "gallery-grid" : redesignStyles.fileGrid}>{resources.isLoading ? <div className="loading">正在加载资源索引…</div> : resources.error ? <div className="empty error-state">加载失败：{resources.error.message}<button type="button" onClick={() => resources.refetch()}>重试</button></div> : resources.data?.items.length ? resources.data.items.map((item) => type === "image" ? <GalleryCard key={item.id} item={item} /> : <ResourceCard key={item.id} item={item} />) : <div className="empty">{type === "image" ? "暂无公开图片" : type === "document" ? "暂无公开教程" : "当前类型暂无资源。完成 AList 配置和同步后会自动显示。"}</div>}</section>
    {(resources.data?.total_pages ?? 0) > 1 && <nav className="pagination" aria-label="资源分页"><button type="button" disabled={page <= 1 || resources.isFetching} onClick={() => navigate({ page: page - 1 })}>上一页</button><span>第 {page} / {resources.data?.total_pages} 页</span><button type="button" disabled={page >= (resources.data?.total_pages ?? 1) || resources.isFetching} onClick={() => navigate({ page: page + 1 })}>下一页</button></nav>}
  </div></PublicShell>;
}
