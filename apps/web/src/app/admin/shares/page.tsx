"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, KeyRound, Plus, RefreshCw, Search, Share2, Trash2 } from "lucide-react";
import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, Share } from "@/lib/api";

type ShareStatus = NonNullable<Share["status"]>;
type Duration = "5m" | "1h" | "6h" | "24h" | "7d" | "permanent";

const objectLabel: Record<string, string> = { resource: "文件", folder: "文件夹", collection: "合集" };
const durationLabel: Record<Duration, string> = { "5m": "5分钟", "1h": "1小时", "6h": "6小时", "24h": "24小时", "7d": "1周", permanent: "永久" };
const statusLabel: Record<ShareStatus, string> = { active: "有效", cancelled: "已取消", expired: "已过期", invalid_target: "目标失效", migration_pending: "待升级" };

function currentStatus(share: Share): ShareStatus {
  return share.status ?? (!share.enabled ? "cancelled" : share.expired ? "expired" : share.target_name == null ? "invalid_target" : "active");
}

export default function SharesPage() {
  const client = useQueryClient();
  const [objectType, setObjectType] = useState<"resource" | "folder" | "collection">("resource");
  const [accessMode, setAccessMode] = useState<"code" | "direct">("code");
  const [duration, setDuration] = useState<Duration>("24h");
  const [objectId, setObjectId] = useState("");
  const [title, setTitle] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ShareStatus>("all");
  const [editingToken, setEditingToken] = useState<string | null>(null);
  const [editingDuration, setEditingDuration] = useState<Duration>("24h");
  const [lastCode, setLastCode] = useState<{ token: string; code: string | null; mode: "code" | "direct" } | null>(null);

  const query = useQuery({ queryKey: ["admin-shares"], queryFn: () => api<{ items: Share[] }>("/api/admin/shares") });
  const create = useMutation({
    mutationFn: () => api<Share>("/api/admin/shares", {
      method: "POST",
      body: JSON.stringify({ object_type: objectType, object_id: objectId.trim(), title, access_mode: accessMode, duration }),
    }),
    onSuccess: (share) => {
      setObjectId("");
      setTitle("");
      setLastCode({ token: share.token, code: share.code ?? null, mode: share.access_mode });
      client.invalidateQueries({ queryKey: ["admin-shares"] });
    },
  });
  const action = useMutation({
    mutationFn: ({ share, body }: { share: Share; body: object }) => api<Share>(`/api/admin/shares/${share.token}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: (share) => {
      if (share.code) setLastCode({ token: share.token, code: share.code, mode: share.access_mode });
      setEditingToken(null);
      client.invalidateQueries({ queryKey: ["admin-shares"] });
    },
  });
  const remove = useMutation({ mutationFn: (token: string) => api(`/api/admin/shares/${token}`, { method: "DELETE" }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-shares"] }) });

  const items = useMemo(() => {
    const list = query.data?.items ?? [];
    const needle = searchQuery.trim().toLowerCase();
    return list.filter((share) => {
      const haystack = `${share.token} ${share.title ?? ""} ${share.target_name ?? ""} ${share.object_id}`.toLowerCase();
      return (!needle || haystack.includes(needle)) && (statusFilter === "all" || currentStatus(share) === statusFilter);
    });
  }, [query.data, searchQuery, statusFilter]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (objectId.trim()) create.mutate();
  }

  function copyShare(share: Share) {
    const link = `${location.origin}/s/${share.token}`;
    const text = share.access_mode === "code" && lastCode?.token === share.token && lastCode.code ? `${link}\n分享码：${lastCode.code}` : link;
    navigator.clipboard.writeText(text);
  }

  function changeObjectType(value: "resource" | "folder" | "collection") {
    setObjectType(value);
    if (value !== "resource") setAccessMode("code");
  }

  return <AdminShell title="分享管理"><div className="admin-page">
    <section className="panel"><h2><Share2 />创建分享</h2><p className="panel-intro">生成 CloudSite 短链接；分享下载固定最多 404 次成功跳转。</p>
      <form className="share-form" onSubmit={submit}>
        <select value={objectType} onChange={(event) => changeObjectType(event.target.value as "resource" | "folder" | "collection")}><option value="resource">文件</option><option value="folder">文件夹</option><option value="collection">合集</option></select>
        <select value={accessMode} onChange={(event) => setAccessMode(event.target.value as "code" | "direct")}><option value="code">分享码访问</option><option value="direct" disabled={objectType !== "resource"}>无分享码直下</option></select>
        <select value={duration} onChange={(event) => setDuration(event.target.value as Duration)}>{Object.entries(durationLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <input value={objectId} onChange={(event) => setObjectId(event.target.value)} placeholder="对象 ID" required />
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="分享标题（可选）" />
        <button className="primary" disabled={create.isPending}><Plus />创建</button>
      </form>
      {lastCode && <p className="share-created">新分享：/s/{lastCode.token}{lastCode.code ? `，分享码：${lastCode.code}` : "，打开即下载"}</p>}
      {create.error && <p className="form-error">{create.error.message}</p>}
      {action.error && <p className="form-error">{action.error.message}</p>}
    </section>

    <section className="panel share-table">
      <div className="panel-toolbar"><div><h2 style={{ marginBottom: 6 }}>分享列表</h2><p>共 {items.length} 条{statusFilter !== "all" ? `（${statusLabel[statusFilter]}）` : ""}</p></div><div className="share-toolbar"><div className="small-search"><Search /><input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索标题 / 分享 ID / 对象名" /></div><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | ShareStatus)}><option value="all">全部</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div></div>
      <div className="table-head share-table-head"><span>分享</span><span>对象</span><span>统计</span><span>有效期</span><span>操作</span></div>
      {items.length ? items.map((share) => {
        const status = currentStatus(share);
        return <div className="table-row share-table-row" key={share.token}>
          <span><Share2 /><b>{share.title || "未命名分享"}<small>/s/{share.token} · {share.access_mode === "direct" ? "无分享码直下" : share.has_code ? "分享码已设置" : "待升级"}</small></b></span>
          <span><b>{share.target_name ?? "对象已失效"}</b><small>{objectLabel[share.object_type] ?? share.object_type} · {share.creator_username ? `用户 ${share.creator_username}` : "管理员"}</small></span>
          <span><b>{share.download_count} / {share.download_limit}</b><small>访问 {share.view_count ?? share.access_count} · 剩余 {share.remaining_downloads}</small></span>
          <span className="share-expiry">{editingToken === share.token ? <><select value={editingDuration} onChange={(event) => setEditingDuration(event.target.value as Duration)}>{Object.entries(durationLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button className="primary" onClick={() => action.mutate({ share, body: { duration: editingDuration } })}>保存</button><button onClick={() => setEditingToken(null)}>取消</button></> : <><b className={status === "expired" ? "warn" : ""}>{share.expires_at ? formatTime(share.expires_at) : "永久"}</b><small>{statusLabel[status]}{share.cancel_reason === "download_limit" ? " · 达到下载上限" : ""}</small><button onClick={() => { setEditingToken(share.token); setEditingDuration("24h"); }}>改期</button></>}</span>
          <span className="share-actions">
            <button title="复制分享信息" onClick={() => copyShare(share)}><Copy /></button>
            <Link title="打开分享" href={`/s/${share.token}`}><ExternalLink /></Link>
            {share.access_mode === "code" && status === "migration_pending" && <button title="升级分享" onClick={() => action.mutate({ share, body: { action: "upgrade" } })}><KeyRound /></button>}
            {share.access_mode === "code" && status !== "migration_pending" && <button title="重置分享码" onClick={() => action.mutate({ share, body: { action: "reset_code" } })}><RefreshCw /></button>}
            <button onClick={() => action.mutate({ share, body: { action: share.enabled ? "cancel" : "restore", duration: editingDuration } })}>{share.enabled ? "取消" : "恢复"}</button>
            <button className="danger" onClick={() => window.confirm("删除这个分享？") && remove.mutate(share.token)}><Trash2 /></button>
          </span>
        </div>;
      }) : <div className="empty">没有匹配的分享记录。</div>}
    </section>
  </div></AdminShell>;
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
