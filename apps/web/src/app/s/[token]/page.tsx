"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock3, Share2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { api, Collection, Folder, Resource, Share } from "@/lib/api";

type SharePayload = { share: Share; target: Resource | Collection | { folder: Folder; folders: Folder[]; resources: Resource[] } };

export default function SharePage() {
  const { token } = useParams<{ token: string }>();
  const query = useQuery({ queryKey: ["share", token], queryFn: () => api<SharePayload>(`/api/shares/${token}`), retry: false });
  if (query.isLoading) return <PublicShell><div className="page loading">正在打开分享…</div></PublicShell>;
  if (!query.data) return <PublicShell><div className="state-page"><strong>失效</strong><h1>分享不可用</h1><p>{query.error?.message || "分享已关闭、已过期或资源不存在。"}</p><Link href="/">返回首页</Link></div></PublicShell>;
  const { share, target } = query.data;
  const resources = share.object_type === "resource" ? [target as Resource] : share.object_type === "collection" ? (target as Collection).items ?? [] : (target as { resources: Resource[] }).resources;
  return <PublicShell><div className="page share-page"><section className="share-heading"><Share2 /><div><h1>{share.title || "CloudSite 资源分享"}</h1><p><Clock3 />{share.expires_at ? `有效至 ${new Date(share.expires_at).toLocaleString("zh-CN")}` : "长期有效"}</p></div></section><section className="resource-grid">{resources.length ? resources.map((item) => <ResourceCard item={item} key={item.id} />) : <div className="empty">分享内容为空。</div>}</section></div></PublicShell>;
}
