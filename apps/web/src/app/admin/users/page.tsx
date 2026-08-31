"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Search, UserRoundCheck, UserRoundX, Users } from "lucide-react";
import { useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";
import { PublicUser } from "@/lib/auth";

type UserPage = { items: PublicUser[]; page: number; page_size: number; total: number; total_pages: number };

export default function AdminUsersPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["admin-users", search, status, page],
    queryFn: () => api<UserPage>(`/api/admin/users?search=${encodeURIComponent(search)}&status=${status}&page=${page}&page_size=20`),
  });
  const updateStatus = useMutation({
    mutationFn: ({ id, status: nextStatus }: { id: number; status: "active" | "disabled" }) => api<PublicUser>(`/api/admin/users/${id}/status`, { method: "PATCH", body: JSON.stringify({ status: nextStatus }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  function toggle(user: PublicUser) {
    if (user.status === "active") {
      if (!window.confirm(`确定停用用户 ${user.username}？\n\n停用后该用户现有登录会话将立即失效。`)) return;
      updateStatus.mutate({ id: user.id, status: "disabled" });
    } else {
      updateStatus.mutate({ id: user.id, status: "active" });
    }
  }

  return <AdminShell title="用户管理"><div className="admin-page">
    <section className="panel users-panel">
      <div className="panel-toolbar"><div><h2><Users />用户列表</h2><p>共 {query.data?.total ?? 0} 个 CloudSite 用户</p></div><div className="users-toolbar"><div className="small-search"><Search /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索用户名" /></div><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="all">全部状态</option><option value="active">正常</option><option value="disabled">已停用</option></select><button title="刷新" onClick={() => query.refetch()}><RotateCcw /></button></div></div>
      <div className="table-head users-table-head"><span>用户</span><span>状态</span><span>注册时间</span><span>最近登录</span><span>操作</span></div>
      {query.isLoading ? <div className="loading">正在读取用户…</div> : query.error ? <div className="empty error-state">加载失败：{query.error.message}</div> : query.data?.items.length ? query.data.items.map((user) => <div className="table-row users-table-row" key={user.id}>
        <span><span className="user-avatar small">{user.username.slice(0, 1).toUpperCase()}</span><b>{user.username}<small>用户 #{user.id}</small></b></span>
        <span><b className={`user-status ${user.status}`}>{user.status === "active" ? "正常" : "已停用"}</b></span>
        <span>{formatTime(user.created_at)}</span>
        <span>{user.last_login_at ? formatTime(user.last_login_at) : "从未登录"}</span>
        <span><button className={user.status === "active" ? "danger" : ""} disabled={updateStatus.isPending} onClick={() => toggle(user)}>{user.status === "active" ? <><UserRoundX />停用</> : <><UserRoundCheck />恢复</>}</button></span>
      </div>) : <div className="empty">没有匹配的用户。</div>}
      {(query.data?.total_pages ?? 0) > 1 && <nav className="pagination"><button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button><span>第 {page} / {query.data?.total_pages} 页</span><button disabled={page >= (query.data?.total_pages ?? 1)} onClick={() => setPage((value) => value + 1)}>下一页</button></nav>}
      {updateStatus.error && <p className="form-error">{updateStatus.error.message}</p>}
    </section>
  </div></AdminShell>;
}

function formatTime(value: string) { return new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }); }
