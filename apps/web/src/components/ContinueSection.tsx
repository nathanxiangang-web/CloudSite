"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Archive } from "lucide-react";
import { formatBytes, Resource } from "@/lib/api";
import { api } from "@/lib/api";

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
  const query = useQuery({
    queryKey: ["home-continue"],
    queryFn: () => api<HistoryResponse>("/api/me/history?page_size=" + limit),
    staleTime: 60_000,
    retry: false,
  });
  if (query.error || !query.data || !query.data.items.length) {
    return <div className="empty">登录后这里会显示你最近浏览过的资源。</div>;
  }
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
