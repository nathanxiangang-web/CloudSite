"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, ExternalLink, KeyRound, RefreshCw, Share2, Trash2 } from "lucide-react";
import Link from "next/link";
import { api, Share } from "@/lib/api";
import { PublicShell } from "@/components/PublicShell";

const statusLabel: Record<string, string> = {
  active: "有效",
  cancelled: "已取消",
  expired: "已过期",
  invalid_target: "文件失效",
  migration_pending: "待升级",
};

export default function MySharesPage() {
  const client = useQueryClient();
  const shares = useQuery({ queryKey: ["my-shares"], queryFn: () => api<{ items: Share[] }>("/api/my/shares") });
  const action = useMutation({
    mutationFn: ({ token, body }: { token: string; body: object }) => api<Share>(`/api/my/shares/${token}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: (share) => {
      if (share.code) navigator.clipboard.writeText(`${location.origin}/s/${share.token}\n提取码：${share.code}`);
      client.invalidateQueries({ queryKey: ["my-shares"] });
    },
  });
  const remove = useMutation({
    mutationFn: (token: string) => api(`/api/my/shares/${token}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["my-shares"] }),
  });

  async function copyShare(share: Share) {
    await navigator.clipboard.writeText(`${location.origin}/s/${share.token}`);
  }

  return <PublicShell><div className="page my-shares-page">
    <Link className="account-back" href="/account"><ArrowLeft />返回账号</Link>
    <header className="my-shares-heading"><div><p>账号资源</p><h1>我的分享</h1><span>只显示由当前账号创建的文件分享。</span></div><Share2 /></header>
    <section className="panel my-shares-panel">
      {shares.isLoading ? <div className="loading">正在读取分享...</div> : shares.error ? <p className="form-error">{shares.error.message}</p> : shares.data?.items.length ? <div className="my-share-list">{shares.data.items.map((share) => {
        const status = share.status ?? (share.enabled ? "active" : "cancelled");
        const isActive = status === "active";
        return <article className="my-share-item" key={share.token}>
          <span className="my-share-icon"><Share2 /></span>
          <div className="my-share-copy"><div><strong>{share.title || share.target_name || "文件分享"}</strong><span className={`my-share-status ${status}`}>{statusLabel[status] ?? status}</span></div><p>{share.target_name || "文件已不可用"}</p><small>/s/{share.token} · {share.access_mode === "code" ? "提取码访问" : "免提取码直下"} · 下载 {share.download_count}/{share.download_limit}</small><small>{share.expires_at ? `有效至 ${formatTime(share.expires_at)}` : "永久有效"}</small></div>
          <div className="my-share-actions">
            <button type="button" title="复制分享链接" onClick={() => copyShare(share)}><Copy /></button>
            <Link title="打开分享" href={`/s/${share.token}`}><ExternalLink /></Link>
            {share.access_mode === "code" && <button type="button" title="重置提取码并复制" disabled={action.isPending} onClick={() => action.mutate({ token: share.token, body: { action: "reset_code" } })}><KeyRound /></button>}
            <button type="button" disabled={action.isPending} onClick={() => action.mutate({ token: share.token, body: { action: isActive ? "cancel" : "restore", duration: "24h" } })}>{isActive ? "取消" : <><RefreshCw />恢复</>}</button>
            <button type="button" className="danger" title="删除分享" disabled={remove.isPending} onClick={() => window.confirm("删除这个分享？") && remove.mutate(share.token)}><Trash2 /></button>
          </div>
        </article>;
      })}</div> : <div className="empty">还没有创建分享。打开任意文件详情即可分享。</div>}
      {(action.error || remove.error) && <p className="form-error">{(action.error || remove.error)?.message}</p>}
    </section>
  </div></PublicShell>;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
