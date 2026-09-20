"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, ExternalLink, KeyRound, RefreshCw, Share2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Share } from "@/lib/api";
import { useAuth } from "@/lib/auth";
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
  const auth = useAuth();
  const router = useRouter();
  const userId = auth.data?.user?.id ?? null;
  const [copied, setCopied] = useState<{ token: string; source: "link" | "reset" } | null>(null);
  const [copyError, setCopyError] = useState("");
  const shares = useQuery({ queryKey: ["my-shares", userId], queryFn: () => api<{ items: Share[] }>("/api/my/shares"), enabled: Boolean(auth.data?.authenticated) });

  useEffect(() => {
    if (!auth.isLoading && !auth.error && !auth.data?.authenticated) router.replace("/login");
  }, [auth.isLoading, auth.error, auth.data?.authenticated, router]);
  const action = useMutation({
    mutationFn: ({ token, body }: { token: string; body: object }) => api<Share>(`/api/my/shares/${token}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async (share) => {
      if (share.code) {
        await copyText(share.token, `${location.origin}/s/${share.token}\n提取码：${share.code}`, "reset");
      }
      client.invalidateQueries({ queryKey: ["my-shares"] });
    },
  });
  const remove = useMutation({
    mutationFn: (token: string) => api(`/api/my/shares/${token}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["my-shares"] }),
  });

  async function copyText(token: string, text: string, source: "link" | "reset") {
    try {
      await navigator.clipboard.writeText(text);
      setCopied({ token, source });
      setCopyError("");
      window.setTimeout(() => setCopied((current) => current?.token === token && current.source === source ? null : current), 2000);
    } catch {
      setCopyError("复制失败，请手动复制分享链接。");
    }
  }

  async function copyShare(share: Share) {
    await copyText(share.token, `${location.origin}/s/${share.token}`, "link");
  }

  return <PublicShell><div className="page my-shares-page">
    <Link className="account-back" href="/account"><ArrowLeft />返回账号</Link>
    <header className="my-shares-heading"><div><p>账号资源</p><h1>我的分享</h1><span>只显示由当前账号创建的文件分享。</span></div><Share2 /></header>
    <section className="panel my-shares-panel">
      {auth.isLoading ? <div className="loading">正在读取账号…</div>
        : auth.error ? <div className="empty error-state">账号状态加载失败：{auth.error.message}<button type="button" onClick={() => auth.refetch()}>重试</button></div>
        : !auth.data?.authenticated ? <div className="loading">正在跳转登录…</div>
        : shares.isLoading ? <div className="loading">正在读取分享...</div>
        : shares.error ? <div className="empty error-state">{shares.error.message}<button type="button" onClick={() => shares.refetch()}>重试</button></div>
        : shares.data?.items.length ? <div className="my-share-list">{shares.data.items.map((share) => {
        const status = share.status ?? (share.enabled ? "active" : "cancelled");
        const isActive = status === "active";
        return <article className="my-share-item" key={share.token}>
          <span className="my-share-icon"><Share2 /></span>
          <div className="my-share-copy"><div><strong>{share.title || share.target_name || "文件分享"}</strong><span className={`my-share-status ${status}`}>{statusLabel[status] ?? status}</span></div><p>{share.target_name || "文件已不可用"}</p><small>/s/{share.token} · {share.access_mode === "code" ? "提取码访问" : "免提取码直下"} · 下载 {share.download_count}/{share.download_limit}</small><small>{share.expires_at ? `有效至 ${formatTime(share.expires_at)}` : "永久有效"}</small></div>
          <div className="my-share-actions">
            <button type="button" title={copied?.token === share.token && copied.source === "link" ? "已复制" : "复制分享链接"} aria-label={copied?.token === share.token && copied.source === "link" ? "分享链接已复制" : "复制分享链接"} onClick={() => copyShare(share)}>{copied?.token === share.token && copied.source === "link" ? <Check /> : <Copy />}</button>
            <Link title="打开分享" href={`/s/${share.token}`}><ExternalLink /></Link>
            {share.access_mode === "code" && <button type="button" title={copied?.token === share.token && copied.source === "reset" ? "新提取码已复制" : "重置提取码并复制"} aria-label={copied?.token === share.token && copied.source === "reset" ? "新提取码已复制" : "重置提取码并复制"} disabled={action.isPending} onClick={() => action.mutate({ token: share.token, body: { action: "reset_code" } })}>{copied?.token === share.token && copied.source === "reset" ? <Check /> : <KeyRound />}</button>}
            <button type="button" disabled={action.isPending} onClick={() => action.mutate({ token: share.token, body: { action: isActive ? "cancel" : "restore", duration: "24h" } })}>{isActive ? "取消" : <><RefreshCw />恢复</>}</button>
            <button type="button" className="danger" title="删除分享" disabled={remove.isPending} onClick={() => window.confirm("删除这个分享？") && remove.mutate(share.token)}><Trash2 /></button>
          </div>
        </article>;
      })}</div> : <div className="empty">还没有创建分享。打开任意文件详情即可分享。</div>}
      {(action.error || remove.error) && <p className="form-error">{(action.error || remove.error)?.message}</p>}
      {copyError && <p className="form-error">{copyError}</p>}
    </section>
  </div></PublicShell>;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
