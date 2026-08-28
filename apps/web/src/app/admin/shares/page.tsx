"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, Plus, Search, Share2, Trash2 } from "lucide-react";
import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, Share } from "@/lib/api";

type ShareStatus = "active" | "expired" | "disabled" | "invalid";

const objectLabel: Record<string, string> = { resource: "文件", folder: "文件夹", collection: "合集" };
const statusLabel: Record<ShareStatus, string> = { active: "有效", expired: "已失效", disabled: "已关闭", invalid: "目标失效" };

function shareStatus(share: Share): ShareStatus {
  if (!share.enabled) return "disabled";
  if (share.expired) return "expired";
  if (share.target_name == null) return "invalid";
  return "active";
}

export default function SharesPage() {
  const client = useQueryClient();
  const [objectType, setObjectType] = useState("resource");
  const [objectId, setObjectId] = useState("");
  const [title, setTitle] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ShareStatus>("all");
  const [editingToken, setEditingToken] = useState<string | null>(null);
  const [editingExpiry, setEditingExpiry] = useState("");

  const query = useQuery({ queryKey: ["admin-shares"], queryFn: () => api<{ items: Share[] }>("/api/admin/shares") });
  const create = useMutation({ mutationFn: () => api<Share>("/api/admin/shares", { method: "POST", body: JSON.stringify({ object_type: objectType, object_id: objectId.trim(), title, expires_at: expiresAt ? new Date(expiresAt).toISOString() : null }) }), onSuccess: () => { setObjectId(""); setTitle(""); setExpiresAt(""); client.invalidateQueries({ queryKey: ["admin-shares"] }); } });
  const toggle = useMutation({ mutationFn: (share: Share) => api(`/api/admin/shares/${share.token}`, { method: "PATCH", body: JSON.stringify({ enabled: !share.enabled }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-shares"] }) });
  const updateExpiry = useMutation({ mutationFn: ({ token, value }: { token: string; value: string }) => api(`/api/admin/shares/${token}`, { method: "PATCH", body: JSON.stringify({ expires_at: value ? new Date(value).toISOString() : null }) }), onSuccess: () => { setEditingToken(null); client.invalidateQueries({ queryKey: ["admin-shares"] }); } });
  const remove = useMutation({ mutationFn: (token: string) => api(`/api/admin/shares/${token}`, { method: "DELETE" }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-shares"] }) });

  const submit = (event: FormEvent) => { event.preventDefault(); if (objectId.trim()) create.mutate(); };

  const items = useMemo(() => {
    const list = query.data?.items ?? [];
    const needle = searchQuery.trim().toLowerCase();
    return list.filter((share) => {
      const haystack = `${share.token} ${share.title ?? ""} ${share.target_name ?? ""} ${share.object_id}`.toLowerCase();
      const matchesSearch = !needle || haystack.includes(needle);
      const matchesFilter = statusFilter === "all" || shareStatus(share) === statusFilter;
      return matchesSearch && matchesFilter;
    });
  }, [query.data, searchQuery, statusFilter]);

  return <AdminShell title="分享管理"><div className="admin-page">
    <section className="panel"><h2><Share2 />创建分享</h2><p className="panel-intro">为文件、文件夹或合集生成稳定分享链接；可设置有效期。</p><form className="share-form" onSubmit={submit}><select value={objectType} onChange={(e) => setObjectType(e.target.value)}><option value="resource">文件</option><option value="folder">文件夹</option><option value="collection">合集</option></select><input value={objectId} onChange={(e) => setObjectId(e.target.value)} placeholder="对象 ID" required /><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="分享标题（可选）" /><input type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} /><button className="primary" disabled={create.isPending}><Plus />创建分享</button></form>{create.error && <p className="form-error">{create.error.message}</p>}</section>

    <section className="panel share-table">
      <div className="panel-toolbar"><div><h2 style={{ marginBottom: 6 }}>分享列表</h2><p>共 {items.length} 条{statusFilter !== "all" ? `（${statusLabel[statusFilter as ShareStatus]}）` : ""}</p></div><div className="share-toolbar"><div className="small-search"><Search /><input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索标题 / 分享 ID / 对象名" /></div><select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as "all" | ShareStatus)}><option value="all">全部</option><option value="active">有效</option><option value="expired">已失效</option><option value="disabled">已关闭</option><option value="invalid">目标失效</option></select></div></div>
      <div className="table-head share-table-head"><span>分享</span><span>对象</span><span>访问</span><span>有效期</span><span>操作</span></div>
      {items.length ? items.map((share) => { const status = shareStatus(share); return <div className="table-row share-table-row" key={share.token}><span><Share2 /><b>{share.title || "未命名分享"}<small>/s/{share.token}</small></b></span><span><b>{share.target_name ?? "对象已失效"}</b><small>{objectLabel[share.object_type] ?? share.object_type} · {share.object_id.slice(0, 16)}…</small></span><span><b>{share.access_count}</b><small>{share.last_accessed_at ? `最近 ${formatTime(share.last_accessed_at)}` : "尚未访问"}</small></span><span className="share-expiry">{editingToken === share.token ? <><input type="datetime-local" value={editingExpiry} onChange={(e) => setEditingExpiry(e.target.value)} /><button className="primary" onClick={() => updateExpiry.mutate({ token: share.token, value: editingExpiry })}>保存</button><button onClick={() => setEditingToken(null)}>取消</button></> : <><b className={status === "expired" ? "warn" : ""}>{share.expires_at ? formatTime(share.expires_at) : "永久"}</b><button onClick={() => { setEditingToken(share.token); setEditingExpiry(share.expires_at ? toLocalInput(share.expires_at) : ""); }}>改期</button></>}</span><span className="share-actions"><button title="复制链接" onClick={() => navigator.clipboard.writeText(`${location.origin}/s/${share.token}`)}><Copy /></button><Link title="打开分享" href={`/s/${share.token}`}><ExternalLink /></Link><button onClick={() => toggle.mutate(share)}>{share.enabled ? "关闭" : "启用"}</button><button className="danger" onClick={() => window.confirm("删除这个分享？") && remove.mutate(share.token)}><Trash2 /></button></span></div>; }) : <div className="empty">没有匹配的分享记录。</div>}
    </section>
  </div></AdminShell>;
}

function toLocalInput(value: string) { const date = new Date(value); if (Number.isNaN(date.getTime())) return ""; const offset = date.getTimezoneOffset() * 60000; return new Date(date.getTime() - offset).toISOString().slice(0, 16); }
function formatTime(value: string) { const date = new Date(value); if (Number.isNaN(date.getTime())) return value; return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
