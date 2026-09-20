"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, ChevronLeft, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";
import { PublicShell } from "@/components/PublicShell";
import { useAuth } from "@/lib/auth";
import {
  fetchMyCatalogFollows,
  unfollowCatalogEntry,
  updateCatalogSubscription,
  type CatalogFollowItem,
} from "@/lib/catalog-client";
import { contentTypeLabel, formatCatalogTimestamp, channelLabel } from "@/lib/catalog";

const PAGE_SIZE = 24;
const FOLLOW_KEY = (userId: number | null) => ["my-catalog-follows", userId] as const;

export default function AccountFollowsPage() {
  const auth = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const userId = auth.data?.user?.id ?? null;
  const requestedPage = Number.parseInt(searchParams.get("page") || "1", 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const baseKey = FOLLOW_KEY(userId);
  const query = useQuery({
    queryKey: [...baseKey, page],
    queryFn: () => fetchMyCatalogFollows({ page, page_size: PAGE_SIZE }),
    enabled: Boolean(auth.data?.authenticated),
    placeholderData: (previous) => previous,
  });
  const totalPages = query.data?.total_pages ?? 0;
  const navigatePage = useCallback((nextPage: number, replace = false) => {
    const values = new URLSearchParams();
    if (nextPage > 1) values.set("page", String(nextPage));
    const href = `/account/follows${values.size ? `?${values.toString()}` : ""}`;
    if (replace) router.replace(href);
    else router.push(href);
  }, [router]);

  useEffect(() => {
    if (!auth.isLoading && !auth.error && !auth.data?.authenticated) router.replace("/login");
  }, [auth.isLoading, auth.error, auth.data?.authenticated, router]);

  useEffect(() => {
    if (!query.data) return;
    const lastPage = Math.max(1, query.data.total_pages || 1);
    if (page > lastPage) navigatePage(lastPage, true);
  }, [page, query.data, navigatePage]);

  const unfollow = useMutation({
    mutationFn: (entryId: string) => unfollowCatalogEntry(entryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-catalog-follows"] });
      if (page > 1 && query.data?.items.length === 1) navigatePage(page - 1);
    },
  });
  const toggleNotify = useMutation({
    mutationFn: ({ entryId, enabled }: { entryId: string; enabled: boolean }) =>
      updateCatalogSubscription(entryId, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-catalog-follows"] }),
  });

  return (
    <PublicShell>
      <div className="page account-library-page">
        <Link href="/account" className="account-back">
          <ChevronLeft />
          返回我的账号
        </Link>
        <header className="account-library-heading">
          <div>
            <Star />
            <span>
              <p>CloudSite 账号</p>
              <h1>我的关注</h1>
            </span>
          </div>
          <Link className="button" href="/account/favorites">
            文件收藏
          </Link>
        </header>
        {auth.isLoading ? (
          <div className="loading">正在读取账号…</div>
        ) : auth.error ? (
          <div className="empty error-state">账号状态加载失败：{auth.error.message}<button type="button" onClick={() => auth.refetch()}>重试</button></div>
        ) : !auth.data?.authenticated ? (
          <div className="loading">正在跳转登录…</div>
        ) : query.isLoading ? (
          <div className="loading">正在读取…</div>
        ) : query.error ? (
          <div className="empty error-state">{query.error.message}<button type="button" onClick={() => query.refetch()}>重试</button></div>
        ) : query.data?.items.length ? (
          <section className="account-resource-list">
            {query.data.items.map((item) => (
              <article key={item.entry_id}>
                <Link href={`/catalog/${item.entry_id}`}>
                  <strong>{item.title}</strong>
                  <span>{contentTypeLabel(item.content_type)}</span>
                  <small>
                    关注于 {formatCatalogTimestamp(item.favorited_at)}
                    {item.latest_release
                      ? ` · 最新版本 ${item.latest_release.title}（${channelLabel(item.latest_release.channel)}）发布于 ${formatCatalogTimestamp(item.latest_release.published_at)}`
                      : " · 暂无已发布版本"}
                  </small>
                </Link>
                <div className="account-follow-actions">
                  <button
                    type="button"
                    aria-label={item.notify_enabled ? "关闭更新通知" : "开启更新通知"}
                    disabled={toggleNotify.isPending}
                    onClick={() => toggleNotify.mutate({ entryId: item.entry_id, enabled: !item.notify_enabled })}
                  >
                    {item.notify_enabled ? <Bell /> : <BellOff />}
                    {item.notify_enabled ? "通知开" : "通知关"}
                  </button>
                  <button
                    type="button"
                    aria-label={`取消关注 ${item.title}`}
                    disabled={unfollow.isPending}
                    onClick={() => unfollow.mutate(item.entry_id)}
                  >
                    <Trash2 />
                    取关
                  </button>
                </div>
              </article>
            ))}
          </section>
        ) : (
          <div className="empty">还没有关注任何资源条目。去 <Link href="/catalog">资源目录</Link> 关注感兴趣的软件吧。</div>
        )}
        {totalPages > 1 && <nav className="pagination" aria-label="我的关注分页"><button type="button" disabled={page <= 1 || query.isFetching} onClick={() => navigatePage(page - 1)}>上一页</button><span>第 {page} / {totalPages} 页 · 共 {query.data?.total ?? 0} 条</span><button type="button" disabled={page >= totalPages || query.isFetching} onClick={() => navigatePage(page + 1)}>下一页</button></nav>}
        {(unfollow.error || toggleNotify.error) && <p className="form-error">{(unfollow.error || toggleNotify.error)?.message}</p>}
      </div>
    </PublicShell>
  );
}
