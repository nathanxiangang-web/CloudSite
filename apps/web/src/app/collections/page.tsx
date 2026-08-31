"use client";

import { useQuery } from "@tanstack/react-query";
import { FileImage, FolderKanban } from "lucide-react";
import ImageAsset from "next/image";
import Link from "next/link";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { api, Collection } from "@/lib/api";

export default function CollectionsPage() {
  const query = useQuery({
    queryKey: ["collections"],
    queryFn: () => api<{ items: Collection[] }>("/api/collections"),
  });
  const collections = query.data?.items ?? [];

  return <PublicShell><div className="page collection-page">
    <section className="library-hero">
      <span className="library-folder type-video"><FolderKanban /></span>
      <div><h1>精选合集</h1><p>跨目录整理的主题资源，一次浏览完整内容。</p><div className="meta">{collections.length} 个合集</div></div>
    </section>
    <h2 className="subheading">全部合集</h2>
    {query.isLoading
      ? <div className="loading">正在加载合集…</div>
      : query.error
        ? <div className="empty error-state">合集暂时不可用：{query.error.message}</div>
        : collections.length
          ? <section className="collection-grid">{collections.map((collection, index) => <Link href={`/collections/${collection.id}`} className="collection-card" key={collection.id}>
            <div className="cover"><ImageAsset src={collection.cover ? `/p/${collection.cover}` : `/assets/collection-${(index % 4) + 1}.png`} alt={collection.name} fill sizes="260px" /></div>
            <strong>{collection.name}</strong>
            <span className="collection-description">{collection.description || "精选资源合集"}</span>
            <div className="collection-meta"><span><FileImage /> {collection.item_count ?? 0} 个资源</span></div>
          </Link>)}</section>
          : <div className="empty">还没有公开合集。</div>}
    <SiteFooter />
  </div></PublicShell>;
}
