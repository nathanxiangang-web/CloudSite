"use client";

import { useQuery } from "@tanstack/react-query";
import { Folder } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { FolderCard } from "@/components/FolderCard";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { api, Folder as FolderType, Resource } from "@/lib/api";

type FolderDetail = {
  folder: FolderType;
  breadcrumbs: Array<{ id: string; name: string }>;
  child_folders: FolderType[];
  resources: { items: Resource[]; total: number; page: number; page_size: number; total_pages: number };
};

export default function FolderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ["folder", id, page], queryFn: () => api<FolderDetail>(`/api/folders/${id}?page=${page}&page_size=24&sort=name&order=asc`) });
  const data = query.data;
  if (query.isLoading) return <PublicShell><div className="page loading">正在加载文件夹索引…</div></PublicShell>;
  if (query.error) return <PublicShell><div className="page state-page"><strong>404</strong><h1>文件夹不可用</h1><p>{query.error.message}</p><Link href="/">返回首页</Link></div></PublicShell>;
  if (!data) return null;
  return <PublicShell><div className="page library-page"><nav className="breadcrumb"><Link href="/">资源库</Link>{data.breadcrumbs.map((item) => <span key={item.id}>› <Link href={`/folder/${item.id}`}>{item.name}</Link></span>)}</nav><section className="library-hero"><span className={`library-folder type-${data.folder.content_type}`}><Folder /></span><div><h1>{data.folder.name}</h1><p>通过安全目录 ID 浏览，底层网盘路径不会公开。</p><div className="meta">{data.child_folders.length} 个子文件夹 · {data.resources.total} 个资源</div></div></section>{data.child_folders.length > 0 && <><h2 className="subheading">子文件夹</h2><section className="folder-grid">{data.child_folders.map((folder) => <FolderCard item={folder} key={folder.id} />)}</section></>}<h2 className="subheading">资源</h2><section className="resource-grid">{data.resources.items.length ? data.resources.items.map((resource) => <ResourceCard item={resource} key={resource.id} />) : <div className="empty">此文件夹暂时没有资源。</div>}</section>{data.resources.total_pages > 1 && <nav className="pagination"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} / {data.resources.total_pages} 页</span><button type="button" disabled={page >= data.resources.total_pages} onClick={() => setPage((value) => value + 1)}>下一页</button></nav>}</div></PublicShell>;
}
