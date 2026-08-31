"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, KeyRound, Pencil, RotateCcw, Search, Trash2, UserPlus, UserRoundCheck, UserRoundX, Users, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";
import { PublicUser } from "@/lib/auth";

type UserPage = { items: PublicUser[]; page: number; page_size: number; total: number; total_pages: number };
type Editor = { kind: "create" | "edit" | "reset"; user?: PublicUser } | null;

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editor, setEditor] = useState<Editor>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");

  const query = useQuery({ queryKey: ["admin-users", search, status, page], queryFn: () => api<UserPage>(`/api/admin/users?search=${encodeURIComponent(search)}&status=${status}&page=${page}&page_size=20`) });
  const detail = useQuery({ queryKey: ["admin-user", selectedId], queryFn: () => api<PublicUser>(`/api/admin/users/${selectedId}`), enabled: selectedId !== null });
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    await queryClient.invalidateQueries({ queryKey: ["admin-user"] });
  };
  const updateStatus = useMutation({
    mutationFn: ({ id, status: nextStatus }: { id: number; status: "active" | "disabled" }) => api<PublicUser>(`/api/admin/users/${id}/status`, { method: "PATCH", body: JSON.stringify({ status: nextStatus }) }),
    onSuccess: refresh,
  });
  const save = useMutation({
    mutationFn: async () => {
      if (editor?.kind === "create") return api<PublicUser>("/api/admin/users", { method: "POST", body: JSON.stringify({ username, password, password_confirm: passwordConfirm }) });
      if (editor?.kind === "edit" && editor.user) return api<PublicUser>(`/api/admin/users/${editor.user.id}`, { method: "PATCH", body: JSON.stringify({ username }) });
      if (editor?.kind === "reset" && editor.user) return api<{ ok: boolean }>(`/api/admin/users/${editor.user.id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: password, new_password_confirm: passwordConfirm }) });
      throw new Error("操作无效");
    },
    onSuccess: async () => { await refresh(); closeEditor(); },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/api/admin/users/${id}`, { method: "DELETE" }),
    onSuccess: async () => { setSelectedId(null); await refresh(); },
  });

  function toggle(user: PublicUser) {
    if (user.status === "active" && !window.confirm(`确定停用用户 ${user.username}？\n\n该用户所有登录会话会立即失效。`)) return;
    updateStatus.mutate({ id: user.id, status: user.status === "active" ? "disabled" : "active" });
  }
  function openEditor(next: NonNullable<Editor>) {
    setEditor(next);
    setUsername(next.user?.username ?? "");
    setPassword("");
    setPasswordConfirm("");
    save.reset();
  }
  function closeEditor() { setEditor(null); setUsername(""); setPassword(""); setPasswordConfirm(""); save.reset(); }
  function submit(event: FormEvent) { event.preventDefault(); save.mutate(); }
  function deleteUser(user: PublicUser) {
    if (window.confirm(`确定删除用户 ${user.username}？\n\n这是软删除：用户名会保留，且该用户所有会话立即失效。`)) remove.mutate(user.id);
  }

  const mutationError = updateStatus.error || remove.error;
  return <AdminShell title="用户管理"><div className="admin-page">
    <section className="panel users-panel">
      <div className="panel-toolbar"><div><h2><Users />用户列表</h2><p>共 {query.data?.total ?? 0} 个 CloudSite 用户</p></div><div className="users-toolbar"><button className="primary" onClick={() => openEditor({ kind: "create" })}><UserPlus />新建用户</button><div className="small-search"><Search /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索用户名" /></div><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="all">当前用户</option><option value="active">正常</option><option value="disabled">已停用</option><option value="deleted">已删除</option></select><button title="刷新" onClick={() => query.refetch()}><RotateCcw /></button></div></div>
      <div className="table-head users-table-head"><span>用户</span><span>状态</span><span>注册时间</span><span>最近登录</span><span>操作</span></div>
      {query.isLoading ? <div className="loading">正在读取用户…</div> : query.error ? <div className="empty error-state">加载失败：{query.error.message}</div> : query.data?.items.length ? query.data.items.map((user) => <div className="table-row users-table-row" key={user.id}>
        <span><span className="user-avatar small">{user.username.slice(0, 1).toUpperCase()}</span><b>{user.username}<small>用户 #{user.id}{user.created_by_admin ? " · 管理员创建" : ""}</small></b></span>
        <span><b className={`user-status ${user.status}`}>{user.status === "active" ? "正常" : user.status === "disabled" ? "已停用" : "已删除"}</b></span>
        <span>{formatTime(user.created_at)}</span>
        <span>{user.last_login_at ? formatTime(user.last_login_at) : "从未登录"}</span>
        <span className="user-actions"><button title="详情" onClick={() => setSelectedId(user.id)}><Eye /></button>{user.status !== "deleted" && <><button title="编辑用户名" onClick={() => openEditor({ kind: "edit", user })}><Pencil /></button><button title="重置密码" onClick={() => openEditor({ kind: "reset", user })}><KeyRound /></button><button className={user.status === "active" ? "danger" : ""} title={user.status === "active" ? "停用" : "恢复"} disabled={updateStatus.isPending} onClick={() => toggle(user)}>{user.status === "active" ? <UserRoundX /> : <UserRoundCheck />}</button><button className="danger" title="删除" disabled={remove.isPending} onClick={() => deleteUser(user)}><Trash2 /></button></>}</span>
      </div>) : <div className="empty">没有匹配的用户。</div>}
      {(query.data?.total_pages ?? 0) > 1 && <nav className="pagination"><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} / {query.data?.total_pages} 页</span><button disabled={page >= (query.data?.total_pages ?? 1)} onClick={() => setPage((value) => value + 1)}>下一页</button></nav>}
      {mutationError && <p className="form-error">{mutationError.message}</p>}
    </section>

    {selectedId !== null && <div className="user-modal-backdrop" role="presentation" onMouseDown={() => setSelectedId(null)}><section className="panel user-modal" role="dialog" aria-modal="true" aria-label="用户详情" onMouseDown={(event) => event.stopPropagation()}><button className="user-modal-close" onClick={() => setSelectedId(null)}><X /></button><h2>用户详情</h2>{detail.isLoading ? <div className="loading">正在读取…</div> : detail.data ? <dl className="user-detail-list"><div><dt>用户 ID</dt><dd>#{detail.data.id}</dd></div><div><dt>用户名</dt><dd>{detail.data.username}</dd></div><div><dt>密码</dt><dd aria-label="密码不可查看">......</dd></div><div><dt>状态</dt><dd>{detail.data.status === "active" ? "正常" : detail.data.status === "disabled" ? "已停用" : "已删除"}</dd></div><div><dt>创建方式</dt><dd>{detail.data.created_by_admin ? "管理员创建" : "用户注册"}</dd></div><div><dt>注册时间</dt><dd>{formatTime(detail.data.created_at)}</dd></div><div><dt>最近登录</dt><dd>{detail.data.last_login_at ? formatTime(detail.data.last_login_at) : "从未登录"}</dd></div><div><dt>密码更新时间</dt><dd>{detail.data.password_changed_at ? formatTime(detail.data.password_changed_at) : "从未修改"}</dd></div></dl> : <p className="form-error">读取用户详情失败</p>}</section></div>}

    {editor && <div className="user-modal-backdrop" role="presentation" onMouseDown={closeEditor}><section className="panel user-modal" role="dialog" aria-modal="true" aria-label="编辑用户" onMouseDown={(event) => event.stopPropagation()}><button className="user-modal-close" onClick={closeEditor}><X /></button><h2>{editor.kind === "create" ? "新建用户" : editor.kind === "edit" ? "修改用户名" : `重置 ${editor.user?.username} 的密码`}</h2><form className="form-stack" onSubmit={submit}>{editor.kind !== "reset" && <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" minLength={2} maxLength={16} pattern={"[A-Za-z0-9_\\-]{2,16}"} required /></label>}{editor.kind !== "edit" && <><label>{editor.kind === "create" ? "密码" : "新密码"}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" minLength={8} maxLength={72} required /></label><label>确认密码<input type="password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} autoComplete="new-password" minLength={8} maxLength={72} required /></label></>}{save.error && <p className="form-error">{save.error.message}</p>}<div className="modal-actions"><button type="button" onClick={closeEditor}>取消</button><button className="primary" disabled={save.isPending}>{save.isPending ? "正在保存…" : "保存"}</button></div></form></section></div>}
  </div></AdminShell>;
}

function formatTime(value: string) { return new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
