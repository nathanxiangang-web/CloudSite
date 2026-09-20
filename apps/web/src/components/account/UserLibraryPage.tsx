"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, Clock3, Heart, PlayCircle, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";
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
const PAGE_SIZE = 24;

const config = {
  favorites: { title: "我的收藏", empty: "还没有收藏资源。", Icon: Heart },
  history: { title: "浏览历史", empty: "还没有浏览记录。", Icon: Clock3 },
  playback: { title: "继续播放", empty: "还没有未看完的视频。", Icon: PlayCircle },
} as const;

export function UserLibraryPage({ kind }: { kind: Kind }) {
  const auth = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const current = config[kind];
  const Icon = current.Icon;
  const userId = auth.data?.user?.id ?? null;
  const requestedPage = Number.parseInt(searchParams.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const baseKey = ["user-library", userId, kind];
  const key = [...baseKey, page];
  const query = useQuery({ queryKey: key, queryFn: () => api<ListResponse>(`/api/me/${kind}?page=${page}&page_size=${PAGE_SIZE}`), enabled: Boolean(auth.data?.authenticated), placeholderData: (previous) => previous });
  const totalPages = Math.ceil((query.data?.total ?? 0) / PAGE_SIZE);
  const navigatePage = useCallback((nextPage: number, replace = false) => {
    const values = new URLSearchParams();
    if (nextPage > 1) values.set("page", String(nextPage));
    const href = `/account/${kind}${values.size ? `?${values.toString()}` : ""}`;
    if (replace) router.replace(href);
    else router.push(href);
  }, [kind, router]);

  useEffect(() => {
    if (!auth.isLoading && !auth.error && !auth.data?.authenticated) router.replace("/login");
  }, [auth.isLoading, auth.error, auth.data?.authenticated, router]);

  useEffect(() => {
    if (!query.data) return;
    const lastPage = Math.max(1, Math.ceil(query.data.total / PAGE_SIZE));
    if (page > lastPage) navigatePage(lastPage, true);
  }, [page, query.data, navigatePage]);

  const remove = useMutation({
    mutationFn: (resourceId: string) => api(`/api/me/${kind}/${resourceId}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: baseKey });
      if (page > 1 && query.data?.items.length === 1) navigatePage(page - 1);
    },
  });
  const clear = useMutation({
    mutationFn: () => api("/api/me/history", { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: baseKey });
      if (page > 1) navigatePage(1);
    },
  });

  return <PublicShell><div className="page account-library-page">
    <Link href="/account" className="account-back"><ChevronLeft />返回我的账号</Link>
    <header className="account-library-heading"><div><Icon /><span><p>CloudSite 账号</p><h1>{current.title}</h1></span></div>{kind === "history" && Boolean(query.data?.items.length) && <button type="button" className="danger" disabled={clear.isPending} onClick={() => clear.mutate()}><Trash2 />清空历史</button>}</header>
    {auth.isLoading ? <div className="loading">正在读取账号…</div>
      : auth.error ? <div className="empty error-state">账号状态加载失败：{auth.error.message}<button type="button" onClick={() => auth.refetch()}>重试</button></div>
      : !auth.data?.authenticated ? <div className="loading">正在跳转登录…</div>
      : query.isLoading ? <div className="loading">正在读取…</div>
      : query.error ? <div className="empty error-state">{query.error.message}<button type="button" onClick={() => query.refetch()}>重试</button></div>
      : query.data?.items.length ? <section className="account-resource-list">{query.data.items.map((item) => <article key={item.id}>
      <Link href={`/resource/${item.id}`}><strong>{item.name}</strong><span>{formatBytes(item.size)} · {item.extension?.toUpperCase() || item.content_type}</span><small>{itemMeta(kind, item)}</small></Link>
      <button type="button" aria-label={`移除 ${item.name}`} disabled={remove.isPending} onClick={() => remove.mutate(item.id)}><Trash2 />移除</button>
    </article>)}</section> : <div className="empty">{current.empty}</div>}
    {totalPages > 1 && <nav className="pagination" aria-label={`${current.title}分页`}><button type="button" disabled={page <= 1 || query.isFetching} onClick={() => navigatePage(page - 1)}>上一页</button><span>第 {page} / {totalPages} 页 · 共 {query.data?.total ?? 0} 条</span><button type="button" disabled={page >= totalPages || query.isFetching} onClick={() => navigatePage(page + 1)}>下一页</button></nav>}
    {Boolean(query.data?.unavailable_count) && <p className="account-library-note">另有 {query.data?.unavailable_count} 条记录因资源已下架或目录未发布而隐藏。</p>}
    {(remove.error || clear.error) && <p className="form-error">{(remove.error || clear.error)?.message}</p>}
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
