"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, FolderKanban, Target, Users, ListChecks, AlignLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { api, Collection } from "@/lib/api";
import { catalogEntryHref, contentTypeLabel } from "@/lib/catalog";

function InfoBlock({ icon: Icon, label, text }: { icon: typeof Target; label: string; text: string }) {
  if (!text.trim()) return null;
  return <div className="collection-info-block"><span className="collection-info-label"><Icon /> {label}</span><p>{text}</p></div>;
}

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({ queryKey: ["collection", id], queryFn: () => api<Collection>(`/api/collections/${id}`) });
  const data = query.data;
  if (query.isLoading) return <PublicShell><div className="page loading">正在加载合集…</div></PublicShell>;
  if (!data) return <PublicShell><div className="page empty">合集不存在。</div></PublicShell>;
  const hasInfo = Boolean(data.goal || data.audience || data.prerequisites || data.item_intro);
  return (
    <PublicShell>
      <div className="page collection-page">
        <section className="library-hero">
          <span className="library-folder type-video"><FolderKanban /></span>
          <div>
            <h1>{data.name}</h1>
            <p>{data.description || "精选资源合集"}</p>
            <div className="meta">{data.items?.length ?? 0} 个资源</div>
          </div>
        </section>
        {hasInfo ? (
          <section className="collection-info">
            <InfoBlock icon={Target} label="目标" text={data.goal} />
            <InfoBlock icon={Users} label="对象" text={data.audience} />
            <InfoBlock icon={ListChecks} label="准备条件" text={data.prerequisites} />
            <InfoBlock icon={AlignLeft} label="条目说明" text={data.item_intro} />
          </section>
        ) : null}
        <h2 className="subheading">合集内容</h2>
        <section className="resource-grid">
          {data.items?.length ? data.items.map((item) => {
            if (item.item_type === "catalog_entry") {
              return (
                <article className="resource-card" key={`ce-${item.catalog_entry_id}`}>
                  <Link href={catalogEntryHref(item.catalog_entry_id)} className="resource-icon-link"><BookOpen size={30} /></Link>
                  <Link href={catalogEntryHref(item.catalog_entry_id)} className="resource-copy">
                    <strong title={item.title}>{item.title}</strong>
                    <span>{contentTypeLabel(item.content_type)}{item.note ? ` · ${item.note}` : ""}</span>
                  </Link>
                </article>
              );
            }
            return <ResourceCard key={`r-${item.id}`} item={item} />;
          }) : <div className="empty">这个合集还没有添加资源。</div>}
        </section>
      </div>
    </PublicShell>
  );
}
