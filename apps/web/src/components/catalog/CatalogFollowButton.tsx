"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Star } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import {
  fetchCatalogFollowStatus,
  followCatalogEntry,
  unfollowCatalogEntry,
  updateCatalogSubscription,
} from "@/lib/catalog-client";

const FOLLOW_STATUS_KEY = (userId: number | null, entryId: string) => ["catalog-follow-status", userId, entryId] as const;

export function CatalogFollowButton({ entryId }: { entryId: string }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const userId = auth.data?.user?.id ?? null;
  const status = useQuery({
    queryKey: FOLLOW_STATUS_KEY(userId, entryId),
    queryFn: () => fetchCatalogFollowStatus(entryId),
    enabled: Boolean(auth.data?.authenticated),
  });

  const follow = useMutation({
    mutationFn: () => followCatalogEntry(entryId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: FOLLOW_STATUS_KEY(userId, entryId) });
      await queryClient.invalidateQueries({ queryKey: ["my-catalog-follows"] });
    },
  });
  const unfollow = useMutation({
    mutationFn: () => unfollowCatalogEntry(entryId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: FOLLOW_STATUS_KEY(userId, entryId) });
      await queryClient.invalidateQueries({ queryKey: ["my-catalog-follows"] });
    },
  });
  const toggleNotify = useMutation({
    mutationFn: (enabled: boolean) => updateCatalogSubscription(entryId, enabled),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: FOLLOW_STATUS_KEY(userId, entryId) });
      await queryClient.invalidateQueries({ queryKey: ["my-catalog-follows"] });
    },
  });

  if (auth.isLoading) {
    return <span className="catalog-follow-button placeholder" aria-busy="true">…</span>;
  }
  if (auth.error) {
    return <button type="button" className="button catalog-follow-button" title={auth.error.message} onClick={() => auth.refetch()}>账号状态不可用 · 重试</button>;
  }
  if (!auth.data?.authenticated) {
    return (
      <Link className="button catalog-follow-button login-required" href={`/login?next=${encodeURIComponent(`/catalog/${entryId}`)}`}>
        <Star size={16} />
        登录后关注
      </Link>
    );
  }

  if (status.isLoading) {
    return <span className="catalog-follow-button placeholder" aria-busy="true">正在读取关注状态…</span>;
  }
  if (status.error) {
    return <button type="button" className="button catalog-follow-button" title={status.error.message} onClick={() => status.refetch()}>关注状态不可用 · 重试</button>;
  }

  const favorited = Boolean(status.data?.favorited);
  const notifyEnabled = Boolean(status.data?.notify_enabled);
  const actionError = follow.error || unfollow.error || toggleNotify.error;

  if (!favorited) {
    return (
      <>
        <button
          type="button"
          className="button primary catalog-follow-button"
          disabled={follow.isPending}
          onClick={() => follow.mutate()}
        >
          <Star size={16} />
          {follow.isPending ? "关注中…" : follow.error ? "关注失败，重试" : "关注"}
        </button>
        {actionError && <small className="form-error">{actionError.message}</small>}
      </>
    );
  }

  return (
    <>
    <div className="catalog-follow-button-group">
      <button
        type="button"
        className="button catalog-follow-button followed"
        disabled={unfollow.isPending}
        onClick={() => unfollow.mutate()}
      >
        <Star size={16} />
        {unfollow.isPending ? "取关中…" : "已关注"}
      </button>
      <button
        type="button"
        className="button catalog-follow-notify"
        disabled={toggleNotify.isPending}
        aria-label={notifyEnabled ? "关闭更新通知" : "开启更新通知"}
        onClick={() => toggleNotify.mutate(!notifyEnabled)}
      >
        {notifyEnabled ? <Bell size={14} /> : <BellOff size={14} />}
        {notifyEnabled ? "通知开" : "通知关"}
      </button>
    </div>
    {actionError && <small className="form-error">{actionError.message}</small>}
    </>
  );
}
