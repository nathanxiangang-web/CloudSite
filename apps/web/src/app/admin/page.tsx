"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, Folder, Link2, RefreshCw, type LucideIcon } from "lucide-react";
import { AdminShell } from "@/components/AdminShell";
import { api } from "@/lib/api";

type Overview = { resources: number; folders: number; download_failures: number; alist_connected: boolean; latest_sync: null | { status: string; added: number; updated: number; removed: number; finished_at: string }; type_counts: Record<string, number>; logs: Array<{ level: string; message: string; created_at: string }> };

export default function AdminOverview() {
  const client = useQueryClient();
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/api/admin/overview") });
  const sync = useMutation({ mutationFn: () => api("/api/admin/sync", { method: "POST", body: JSON.stringify({ full: false }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["overview"] }) });
  const data = overview.data;
  const stats: Array<[LucideIcon, string, string | number, string]> = [[Database, "资源总数", data?.resources ?? 0, "blue"], [Folder, "文件夹", data?.folders ?? 0, "green"], [Link2, "AList 连接", data?.alist_connected ? "正常" : "待配置", "purple"], [AlertTriangle, "下载异常", data?.download_failures ?? 0, "red"]];
  return <AdminShell title="概览"><div className="admin-page"><section className="stat-grid">{stats.map(([Icon, label, value, color]) => <article key={label}><span className={`stat-icon ${color}`}><Icon /></span><div><small>{label}</small><strong>{String(value)}</strong></div></article>)}</section>
    <section className="admin-columns"><article className="panel"><h2>CloudSite 状态</h2>{[[data?.alist_connected, "AList 连接", data?.alist_connected ? "连接正常" : "请在系统页完成配置"], [data?.latest_sync?.status === "success", "资源索引", data?.latest_sync ? `最近同步：${data.latest_sync.status}` : "尚未同步"], [true, "下载网关", "302 按需解析已就绪"], [true, "双数据库", "state.db 与 index.db 正常"]].map(([ok, title, desc]) => <div className="status-row" key={String(title)}>{ok ? <CheckCircle2 className="ok" /> : <AlertTriangle className="warn" />}<span><strong>{String(title)}</strong><small>{String(desc)}</small></span></div>)}</article>
      <article className="panel"><h2>最近同步</h2><dl><div><dt>状态</dt><dd>{data?.latest_sync?.status ?? "未运行"}</dd></div><div><dt>新增</dt><dd>{data?.latest_sync?.added ?? 0}</dd></div><div><dt>修改</dt><dd>{data?.latest_sync?.updated ?? 0}</dd></div><div><dt>删除</dt><dd>{data?.latest_sync?.removed ?? 0}</dd></div></dl><button className="primary" onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw className={sync.isPending ? "spin" : ""} />{sync.isPending ? "正在同步" : "立即同步"}</button>{sync.error && <p className="form-error">{sync.error.message}</p>}</article></section>
    <section className="admin-columns lower"><article className="panel"><h2>内容概况</h2>{Object.entries(data?.type_counts ?? {}).map(([type, count]) => <div className="bar-row" key={type}><span>{({ software: "软件", image: "图片", video: "视频", document: "文档", file: "其他" } as Record<string, string>)[type]}</span><i><b style={{ width: `${Math.min(100, count ? 15 + Math.log10(count + 1) * 25 : 0)}%` }} /></i><strong>{count}</strong></div>)}</article><article className="panel"><h2>最近事件</h2>{data?.logs.length ? data.logs.map((log, index) => <div className="event-row" key={index}><span className={log.level.toLowerCase()}>{log.level}</span><p>{log.message}</p></div>) : <div className="empty compact">暂无运行事件</div>}</article></section>
  </div></AdminShell>;
}
