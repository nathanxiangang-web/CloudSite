"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardList } from "lucide-react";
import Link from "next/link";
import { PublicShell } from "@/components/PublicShell";
import { SiteFooter } from "@/components/SiteFooter";
import { api } from "@/lib/api";

type Submission = {
  id: number;
  resource_name: string;
  resource_type: string;
  description: string;
  source_url: string;
  download_url: string;
  status: "pending" | "approved" | "rejected" | "published";
  admin_note: string;
  reviewed_at: string | null;
  created_at: string;
};

const statusLabel: Record<Submission["status"], string> = { pending: "待审核", approved: "已通过", rejected: "已拒绝", published: "已发布" };
const typeLabel: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "文件" };

function formatTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export default function MySubmissionsPage() {
  const query = useQuery({ queryKey: ["my-submissions"], queryFn: () => api<{ items: Submission[] }>("/api/submissions/mine") });
  const items = query.data?.items ?? [];

  return <PublicShell><div className="page account-library-page">
    <section className="account-library-heading">
      <div><ClipboardList size={42} /><div><p>你提交过的资源投稿</p><h1>我的投稿</h1></div></div>
    </section>
    {query.isLoading ? <div className="loading">正在加载…</div>
      : query.error ? <div className="empty error-state">加载失败：{query.error.message}</div>
      : items.length === 0 ? <div className="empty">你还没有提交过投稿。前往 <Link href="/submit">资源投稿</Link> 提交第一个资源。</div>
      : <div className="account-resource-list">
        {items.map((item) => <article key={item.id}>
          <div>
            <strong>{item.resource_name}</strong>
            <small>{typeLabel[item.resource_type] ?? item.resource_type} · {formatTime(item.created_at)}</small>
            {item.admin_note && <small className="submission-admin-note">审核备注：{item.admin_note}</small>}
          </div>
          <b className={`submission-status ${item.status}`}>{statusLabel[item.status]}</b>
        </article>)}
      </div>}
    <SiteFooter />
  </div></PublicShell>;
}
