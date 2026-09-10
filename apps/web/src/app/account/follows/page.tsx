"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, ChevronLeft, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { PublicShell } from "@/components/PublicShell";
import { useAuth } from "@/lib/auth";
import {
  fetchMyCatalogFollows,
  unfollowCatalogEntry,
  updateCatalogSubscription,
  type CatalogFollowItem,
} from "@/lib/catalog-client";
import { contentTypeLabel, formatCatalogTimestamp, channelLabel } from "@/lib/catalog";

const FOLLOW_KEY = (userId: number | null) => ["my-catalog-follows", userId] as const;

export default function AccountFollowsPage() {
  const auth = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const userId = auth.data?.user?.id ?? null;
  const query = useQuery({
    queryKey: FOLLOW_KEY(userId),
    queryFn: () => fetchMyCatalogFollows({ page: 1, page_size: 100 }),
    enabled: Boolean(auth.data?.authenticated),
  });

  useEffect(() => {
    if (!auth.isLoading && !auth.data?.authenticated) router.replace("/login");
  }, [auth.isLoading, auth.data?.authenticated, router]);

  const unfollow = useMutation({
    mutationFn: (entryId: string) => unfollowCatalogEntry(entryId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-catalog-follows"] }),
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
        {query.isLoading ? (
          <div className="loading">正在读取…</div>
        ) : query.error ? (
          <div className="empty error-state">{query.error.message}</div>
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
      </div>
    </PublicShell>
  );
}
