"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Clock3, Heart, PlayCircle, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { PublicShell } from "@/components/PublicShell";
import { api, formatBytes, Resource } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Kind = "favorites" | "history" | "playback";
type UserResource = Resource & {
  favorited_at?: string;
  last_viewed_at?: string;
  view_count?: number;
  position_seconds?: number;
  duration_seconds?: number;
  last_played_at?: string;
};
type ListResponse = { items: UserResource[]; total: number; unavailable_count: number };

const config = {
  favorites: { title: "我的收藏", empty: "还没有收藏资源。", Icon: Heart },
  history: { title: "浏览历史", empty: "还没有浏览记录。", Icon: Clock3 },
  playback: { title: "继续播放", empty: "还没有未看完的视频。", Icon: PlayCircle },
} as const;

export function UserLibraryPage({ kind }: { kind: Kind }) {
  const auth = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const current = config[kind];
  const Icon = current.Icon;
  const key = ["user-library", kind];
  const query = useQuery({ queryKey: key, queryFn: () => api<ListResponse>(`/api/me/${kind}`), enabled: Boolean(auth.data?.authenticated) });

  useEffect(() => {
    if (!auth.isLoading && !auth.data?.authenticated) router.replace("/login");
  }, [auth.isLoading, auth.data?.authenticated, router]);

  const remove = useMutation({
    mutationFn: (resourceId: string) => api(`/api/me/${kind}/${resourceId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const clear = useMutation({
    mutationFn: () => api("/api/me/history", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
  });

  return <PublicShell><div className="page account-library-page">
    <Link href="/account" className="account-back"><ChevronLeft />返回我的账号</Link>
    <header className="account-library-heading"><div><Icon /><span><p>CloudSite 账号</p><h1>{current.title}</h1></span></div>{kind === "history" && Boolean(query.data?.items.length) && <button type="button" className="danger" disabled={clear.isPending} onClick={() => clear.mutate()}><Trash2 />清空历史</button>}</header>
    {query.isLoading ? <div className="loading">正在读取…</div> : query.error ? <div className="empty error-state">{query.error.message}</div> : query.data?.items.length ? <section className="account-resource-list">{query.data.items.map((item) => <article key={item.id}>
      <Link href={`/resource/${item.id}`}><strong>{item.name}</strong><span>{formatBytes(item.size)} · {item.extension?.toUpperCase() || item.content_type}</span><small>{itemMeta(kind, item)}</small></Link>
      <button type="button" aria-label={`移除 ${item.name}`} disabled={remove.isPending} onClick={() => remove.mutate(item.id)}><Trash2 />移除</button>
    </article>)}</section> : <div className="empty">{current.empty}</div>}
    {Boolean(query.data?.unavailable_count) && <p className="account-library-note">另有 {query.data?.unavailable_count} 条记录因资源已下架或目录未发布而隐藏。</p>}
  </div></PublicShell>;
}

function itemMeta(kind: Kind, item: UserResource) {
  if (kind === "favorites") return item.favorited_at ? `收藏于 ${formatDate(item.favorited_at)}` : "已收藏";
  if (kind === "history") return `${formatDate(item.last_viewed_at)} · 浏览 ${item.view_count || 1} 次`;
  const position = item.position_seconds || 0;
  const duration = item.duration_seconds || 0;
  return `${formatClock(position)} / ${formatClock(duration)} · ${formatDate(item.last_played_at)}`;
}

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString("zh-CN") : "最近";
}

function formatClock(value: number) {
  const seconds = Math.max(0, Math.floor(value));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
