"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Archive } from "lucide-react";
import { formatBytes, Resource } from "@/lib/api";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type HistoryResponse = { items: (Resource & { last_viewed_at: string; view_count: number })[]; total: number };

function formatTime(value: string | null) {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近";
  const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3600000));
  if (hours < 1) return "刚刚";
  if (hours < 24) return `${hours} 小时前`;
  if (hours < 168) return `${Math.floor(hours / 24)} 天前`;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export function ContinueSection({ limit }: { limit: number }) {
  const auth = useAuth();
  const userId = auth.data?.user?.id ?? null;
  const query = useQuery({
    queryKey: ["home-continue", userId, limit],
    queryFn: () => api<HistoryResponse>("/api/me/history?page_size=" + limit),
    enabled: Boolean(auth.data?.authenticated && userId !== null),
    staleTime: 60_000,
    retry: false,
  });

  if (auth.isLoading) return <div className="loading">正在读取账号状态…</div>;
  if (auth.error) return <div className="empty error-state">账号状态加载失败：{auth.error.message}<button type="button" onClick={() => auth.refetch()}>重试</button></div>;
  if (!auth.data?.authenticated) return <div className="empty">登录后这里会显示你最近浏览过的资源。</div>;
  if (query.isLoading) return <div className="loading">正在读取最近浏览…</div>;
  if (query.error) return <div className="empty error-state">最近浏览暂时不可用：{query.error.message}<button type="button" onClick={() => query.refetch()}>重试</button></div>;
  if (!query.data?.items.length) return <div className="empty">还没有浏览记录。</div>;
  const items = query.data.items.slice(0, limit);
  return <section className="recent-table">
    {items.map((item) => (
      <Link href={`/resource/${item.id}`} className="recent-row" key={item.id}>
        <span className="recent-icon type-file"><Archive /></span>
        <strong title={item.name}>{item.name}</strong>
        <span>{formatBytes(item.size)}</span>
        <span>{formatTime(item.last_viewed_at)}</span>
      </Link>
    ))}
  </section>;
}
