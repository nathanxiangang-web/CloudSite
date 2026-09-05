"use client";

import { useQuery } from "@tanstack/react-query";
import { Folder, Grid2X2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { FolderCard } from "@/components/FolderCard";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { GalleryCard } from "@/components/GalleryCard";
import { api, Folder as FolderType, Resource } from "@/lib/api";

const labels: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "全部文件" };
type ResourcePage = { items: Resource[]; total: number; page: number; page_size: number; total_pages: number };

export default function ResourceLibrary() {
  const { type } = useParams<{ type: string }>();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("modified_at");
  const label = labels[type] || "资源";
  const resources = useQuery({ queryKey: ["resources", type, page, sort], queryFn: () => api<ResourcePage>(`/api/resources?type=${encodeURIComponent(type)}&page=${page}&page_size=24&sort=${sort}&order=${sort === "name" ? "asc" : "desc"}`) });
  const folders = useQuery({ queryKey: ["folders", type], queryFn: () => api<{ items: FolderType[] }>(`/api/folders?content_type=${encodeURIComponent(type)}`) });
  const roots = folders.data?.items.filter((folder) => folder.depth <= 1).slice(0, 8) ?? [];
  return <PublicShell><div className="page library-page"><div className="breadcrumb">资源库 <span>›</span> {label}</div><section className="library-hero"><span className={`library-folder type-${type}`}><Folder /></span><div><h1>{label}资源库</h1><p>目录与资源来自 CloudSite 索引，页面不会实时读取或暴露底层网盘路径。</p><div className="meta">{resources.data?.total ?? 0} 个资源 · {folders.data?.items.length ?? 0} 个文件夹</div></div></section>
    {roots.length > 0 && <><h2 className="subheading">文件夹</h2><section className="folder-grid">{roots.map((folder) => <FolderCard item={folder} key={folder.id} />)}</section></>}
    <div className="library-toolbar"><h2>全部资源</h2><div><label className="library-sort">排序<select value={sort} onChange={(event) => { setSort(event.target.value); setPage(1); }}><option value="modified_at">最近更新</option><option value="name">名称</option><option value="size">文件大小</option></select></label><button className="selected" aria-label="网格视图"><Grid2X2 /></button></div></div>
    <section className={type === "image" ? "gallery-grid" : "resource-grid"}>{resources.isLoading ? <div className="loading">正在加载资源索引…</div> : resources.error ? <div className="empty error-state">加载失败：{resources.error.message}</div> : resources.data?.items.length ? resources.data.items.map((item) => type === "image" ? <GalleryCard key={item.id} item={item} /> : <ResourceCard key={item.id} item={item} />) : <div className="empty">{type === "image" ? "暂无公开图片" : type === "document" ? "暂无公开教程" : "当前类型暂无资源。完成 AList 配置和同步后会自动显示。"}</div>}</section>
    {(resources.data?.total_pages ?? 0) > 1 && <nav className="pagination" aria-label="资源分页"><button type="button" disabled={page <= 1 || resources.isFetching} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} / {resources.data?.total_pages} 页</span><button type="button" disabled={page >= (resources.data?.total_pages ?? 1) || resources.isFetching} onClick={() => setPage((value) => value + 1)}>下一页</button></nav>}
  </div></PublicShell>;
}
