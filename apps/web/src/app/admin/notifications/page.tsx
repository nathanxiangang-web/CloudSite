"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Pin, PinOff, Plus, Power, Save, Trash2, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";

type Notification = {
  id: number;
  user_id: number | null;
  title: string;
  body: string;
  level: "info" | "success" | "warning" | "important";
  pinned: boolean;
  enabled: boolean;
  source: string;
  published_at: string;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
};

const levelLabel: Record<Notification["level"], string> = { info: "普通", success: "成功", warning: "警告", important: "重要" };

function formatTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function toLocalInput(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromLocalInput(value: string) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

const emptyForm = { title: "", body: "", level: "info" as Notification["level"], pinned: false, enabled: true, expires_at: "" };

export default function AdminNotificationsPage() {
  const client = useQueryClient();
  const [editingId, setEditingId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const query = useQuery({ queryKey: ["admin-notifications"], queryFn: () => api<{ items: Notification[] }>("/api/admin/notifications") });

  const save = useMutation({
    mutationFn: () => {
      const payload = { title: form.title, body: form.body, level: form.level, pinned: form.pinned, enabled: form.enabled, expires_at: fromLocalInput(form.expires_at) };
      if (editingId !== null) return api<Notification>(`/api/admin/notifications/${editingId}`, { method: "PATCH", body: JSON.stringify(payload) });
      return api<Notification>("/api/admin/notifications", { method: "POST", body: JSON.stringify(payload) });
    },
    onSuccess: () => { setEditingId(null); setCreating(false); setForm(emptyForm); client.invalidateQueries({ queryKey: ["admin-notifications"] }); },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/api/admin/notifications/${id}`, { method: "DELETE" }),
    onSuccess: () => { setDeletingId(null); client.invalidateQueries({ queryKey: ["admin-notifications"] }); },
  });

  const toggle = useMutation({
    mutationFn: (item: Notification) => api<Notification>(`/api/admin/notifications/${item.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !item.enabled }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin-notifications"] }),
  });

  const togglePin = useMutation({
    mutationFn: (item: Notification) => api<Notification>(`/api/admin/notifications/${item.id}`, { method: "PATCH", body: JSON.stringify({ pinned: !item.pinned }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin-notifications"] }),
  });

  function openCreate() { setCreating(true); setEditingId(null); setForm(emptyForm); }
  function openEdit(item: Notification) { setEditingId(item.id); setCreating(false); setForm({ title: item.title, body: item.body, level: item.level, pinned: item.pinned, enabled: item.enabled, expires_at: toLocalInput(item.expires_at) }); }
  function closeForm() { setEditingId(null); setCreating(false); setForm(emptyForm); }

  function onSubmit(event: FormEvent) { event.preventDefault(); save.mutate(); }

  const items = query.data?.items ?? [];
  const showForm = creating || editingId !== null;

  return <AdminShell title="通知管理"><div className="admin-page">
    <section className="panel">
      <div className="panel-toolbar"><div><h2><Bell />通知管理</h2><p>共 {items.length} 条通知</p></div><div className="share-toolbar"><button className="primary" onClick={openCreate}><Plus size={16} />新建通知</button></div></div>
      <div className="table-head notification-table-head"><span>标题</span><span>级别</span><span>范围</span><span>状态</span><span>发布时间</span><span>操作</span></div>
      {query.isLoading ? <div className="loading">正在读取通知…</div> : items.length ? items.map((item) => <div className="table-row notification-table-row" key={item.id}>
        <span><b>{item.title}{item.pinned && <Pin size={12} className="notification-pin-inline" />}</b><small>{item.body.slice(0, 40) || "—"}</small></span>
        <span><b className={`notification-level level-${item.level}`}>{levelLabel[item.level]}</b></span>
        <span>{item.user_id === null ? <b>全站</b> : <small>用户 #{item.user_id}</small>}</span>
        <span><b className={item.enabled ? "status-on" : "status-off"}>{item.enabled ? "启用" : "禁用"}</b>{item.source === "submission" && <small>系统</small>}</span>
        <span>{formatTime(item.published_at)}</span>
        <span className="notification-actions">
          {deletingId === item.id ? <span className="submission-delete-confirm">
            <button className="danger" disabled={remove.isPending} onClick={() => remove.mutate(item.id)}>{remove.isPending ? "删除中…" : "确认删除"}</button>
            <button onClick={() => setDeletingId(null)}>取消</button>
          </span> : <>
            <button title={item.pinned ? "取消置顶" : "置顶"} onClick={() => togglePin.mutate(item)}>{item.pinned ? <PinOff size={16} /> : <Pin size={16} />}</button>
            <button title={item.enabled ? "禁用" : "启用"} onClick={() => toggle.mutate(item)}><Power size={16} /></button>
            <button title="编辑" onClick={() => openEdit(item)}>编辑</button>
            <button className="danger-icon" title="删除" onClick={() => setDeletingId(item.id)}><Trash2 size={16} /></button>
          </>}
        </span>
      </div>) : <div className="empty">暂无通知。</div>}
      {query.error && <p className="form-error">{query.error.message}</p>}
    </section>

    {showForm && <div className="submission-detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeForm(); }}>
      <section className="panel notification-form" role="dialog" aria-modal="true" aria-label={editingId !== null ? "编辑通知" : "新建通知"} onMouseDown={(event) => event.stopPropagation()}>
        <div className="notification-form-head"><h2>{editingId !== null ? "编辑通知" : "新建通知"}</h2><button onClick={closeForm} aria-label="关闭"><X size={18} /></button></div>
        <form onSubmit={onSubmit}>
          <label className="form-row"><span>标题</span><input value={form.title} onChange={(event) => setForm((value) => ({ ...value, title: event.target.value }))} placeholder="通知标题" maxLength={200} required /></label>
          <label className="form-row"><span>正文</span><textarea value={form.body} onChange={(event) => setForm((value) => ({ ...value, body: event.target.value }))} placeholder="通知正文（可选）" maxLength={4000} rows={5} /></label>
          <div className="form-row-inline">
            <label className="form-row"><span>级别</span><select value={form.level} onChange={(event) => setForm((value) => ({ ...value, level: event.target.value as Notification["level"] }))}>{Object.entries(levelLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="form-row"><span>过期时间</span><input type="datetime-local" value={form.expires_at} onChange={(event) => setForm((value) => ({ ...value, expires_at: event.target.value }))} /></label>
          </div>
          <div className="form-row-inline">
            <label className="checkbox-row"><input type="checkbox" checked={form.pinned} onChange={(event) => setForm((value) => ({ ...value, pinned: event.target.checked }))} /><span>置顶</span></label>
            <label className="checkbox-row"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm((value) => ({ ...value, enabled: event.target.checked }))} /><span>启用</span></label>
          </div>
          <p className="form-hint">手动创建的通知为全站广播，所有登录用户可见。投稿审核产生的个人通知仅对该投稿用户可见。</p>
          {save.error && <p className="form-error">{save.error.message}</p>}
          <div className="form-actions"><button type="button" onClick={closeForm}>取消</button><button type="submit" className="primary" disabled={save.isPending}><Save size={16} />{save.isPending ? "保存中…" : "保存"}</button></div>
        </form>
      </section>
    </div>}
  </div></AdminShell>;
}
