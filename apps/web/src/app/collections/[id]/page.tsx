"use client";

import { useQuery } from "@tanstack/react-query";
import { FolderKanban } from "lucide-react";
import { useParams } from "next/navigation";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { api, Collection } from "@/lib/api";

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({ queryKey: ["collection", id], queryFn: () => api<Collection>(`/api/collections/${id}`) });
  const data = query.data;
  if (query.isLoading) return <PublicShell><div className="page loading">正在加载合集…</div></PublicShell>;
  if (!data) return <PublicShell><div className="page empty">合集不存在。</div></PublicShell>;
  return <PublicShell><div className="page collection-page"><section className="library-hero"><span className="library-folder type-video"><FolderKanban /></span><div><h1>{data.name}</h1><p>{data.description || "精选资源合集"}</p><div className="meta">{data.items?.length ?? 0} 个资源</div></div></section><h2 className="subheading">合集内容</h2><section className="resource-grid">{data.items?.length ? data.items.map((item) => <ResourceCard key={item.id} item={item} />) : <div className="empty">这个合集还没有添加资源。</div>}</section></div></PublicShell>;
}
