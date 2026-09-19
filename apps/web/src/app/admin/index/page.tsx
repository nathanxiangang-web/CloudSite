"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Database, Folder, RefreshCw, Search, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, Folder as FolderType } from "@/lib/api";

type SyncRun = {
  id: number;
  sync_type: string;
  status: string;
  folders_scanned: number;
  resources_scanned: number;
  added_count: number;
  updated_count: number;
  removed_count: number;
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  error_message: string;
  current_path?: string;
  roots_completed?: number;
  roots_total?: number;
};
type IndexSummary = { folders: number; resources: number; syncing: boolean; latest_sync: SyncRun | null };
type Mapping = { id: number; content_type: string; display_name: string; alist_path: string; enabled: boolean };

const typeNames: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "普通文件" };
const runStatusLabel: Record<string, string> = { success: "已完成", failed: "失败", running: "进行中", pending: "等待中", partial: "部分完成", cancelled: "已取消", skipped: "已跳过" };
function labelOf(map: Record<string, string>, value: string) { return map[value] ?? value; }

function TreeNode({ node, childrenByParent, expanded, selectedId, toggle, select }: {
  node: FolderType;
  childrenByParent: Map<string | null, FolderType[]>;
  expanded: Set<string>;
  selectedId: string | null;
  toggle: (id: string) => void;
  select: (id: string) => void;
}) {
  const children = childrenByParent.get(node.id) ?? [];
  const open = expanded.has(node.id);
  return <li><div className={selectedId === node.id ? "folder-tree-row selected" : "folder-tree-row"}>
    <button className="tree-toggle" type="button" disabled={!children.length} onClick={() => toggle(node.id)} aria-label={open ? "收起" : "展开"}>{children.length ? open ? <ChevronDown /> : <ChevronRight /> : <span />}</button>
    <button className="tree-select" type="button" onClick={() => select(node.id)}><Folder /><span><strong>{node.name}</strong><small>{node.resource_count} 个资源 · {node.child_folder_count} 个子目录</small></span></button>
  </div>{open && children.length > 0 && <ul>{children.map((child) => <TreeNode key={child.id} node={child} childrenByParent={childrenByParent} expanded={expanded} selectedId={selectedId} toggle={toggle} select={select} />)}</ul>}</li>;
}

export default function IndexPage() {
  const client = useQueryClient();
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const summary = useQuery({ queryKey: ["index-summary"], queryFn: () => api<IndexSummary>("/api/admin/index/summary"), refetchInterval: (query) => query.state.data?.syncing ? 2000 : false });
  const folders = useQuery({ queryKey: ["admin-folders"], queryFn: () => api<{ items: FolderType[] }>("/api/admin/index/folders") });
  const mappings = useQuery({ queryKey: ["mappings"], queryFn: () => api<{ items: Mapping[] }>("/api/admin/root-mappings") });
  const detail = useQuery({ queryKey: ["admin-folder", selectedId], queryFn: () => api<FolderType & { direct_resource_count: number }>(`/api/admin/index/folders/${selectedId}`), enabled: Boolean(selectedId) });
  const refresh = () => { client.invalidateQueries({ queryKey: ["index-summary"] }); client.invalidateQueries({ queryKey: ["admin-folders"] }); client.invalidateQueries({ queryKey: ["admin-folder"] }); };
  const sync = useMutation({ mutationFn: (full: boolean) => api("/api/admin/sync", { method: "POST", body: JSON.stringify({ full }) }), onSuccess: refresh });
  const cancelSync = useMutation({ mutationFn: () => api("/api/admin/sync/cancel", { method: "POST" }), onSuccess: refresh });
  const wasSyncing = useRef(false);

  useEffect(() => {
    const currentSyncing = summary.data?.syncing ?? false;
    if (wasSyncing.current && !currentSyncing) {
      void client.invalidateQueries({ queryKey: ["admin-folders"] });
      void client.invalidateQueries({ queryKey: ["admin-folder"] });
    }
    wasSyncing.current = currentSyncing;
  }, [client, summary.data?.syncing]);

  const childrenByParent = useMemo(() => {
    const map = new Map<string | null, FolderType[]>();
    for (const folder of folders.data?.items ?? []) {
      const list = map.get(folder.parent_id) ?? [];
      list.push(folder);
      map.set(folder.parent_id, list);
    }
    for (const list of map.values()) list.sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
    return map;
  }, [folders.data]);
  const roots = childrenByParent.get(null) ?? [];
  const filtered = (folders.data?.items ?? []).filter((item) => `${item.name} ${item.path}`.toLowerCase().includes(filter.toLowerCase()));
  const latest = summary.data?.latest_sync;
  const syncing = summary.data?.syncing ?? false;
  const toggle = (id: string) => setExpanded((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });

  const syncStatusIcon = syncing ? <Loader2 className="spin" /> : latest?.status === "success" ? <CheckCircle2 className="ok" /> : latest?.status === "failed" ? <AlertTriangle className="warn" /> : <Database />;
  const syncStatusText = syncing ? "进行中" : latest ? labelOf(runStatusLabel, latest.status) : "未运行";
  const syncDetail = latest && !syncing ? `${latest.added_count > 0 ? `+${latest.added_count} ` : ""}${latest.updated_count > 0 ? `~${latest.updated_count} ` : ""}${latest.removed_count > 0 ? `-${latest.removed_count}` : ""}${latest.added_count + latest.updated_count + latest.removed_count === 0 ? "无变化" : ""} · ${(latest.duration_ms / 1000).toFixed(1)}s` : syncing && latest ? `${latest.roots_completed} / ${latest.roots_total} 根目录 · ${latest.resources_scanned} 资源 · ${(latest.duration_ms / 1000).toFixed(0)}s` : "";

  return <AdminShell title="内容索引"><div className="admin-page index-admin-page">
    <section className="index-summary-grid">
      <article><Database /><span><small>索引资源</small><strong>{summary.data?.resources ?? 0}</strong></span></article>
      <article><Folder /><span><small>目录数量</small><strong>{summary.data?.folders ?? 0}</strong></span></article>
      <article>{syncStatusIcon}<span><small>最近同步</small><strong>{syncStatusText}</strong><small>{syncDetail}</small></span></article>
    </section>
    <section className="panel index-control-panel">
      <div className="index-control-info"><h2>Indexing v2</h2><p>扫描 AList 目录并同步到索引数据库</p></div>
      <div className="index-actions">
        {syncing ? <button type="button" className="danger" disabled={cancelSync.isPending} onClick={() => cancelSync.mutate()}><AlertTriangle />取消同步</button> : <button type="button" className="primary" disabled={sync.isPending} onClick={() => sync.mutate(false)}><RefreshCw />立即同步</button>}
      </div>
      {sync.error && <p className="form-error">{sync.error.message}</p>}
      {syncing && latest && <div className="sync-progress-bar"><div className="sync-progress-info"><span>{latest.current_path ? `扫描中：${latest.current_path}` : "处理中…"}</span><span>{latest.roots_completed} / {latest.roots_total} 根目录 · {latest.resources_scanned} 资源</span></div></div>}
    </section>
    <section className="index-workspace">
      <article className="panel folder-tree-panel">
        <div className="panel-toolbar"><div><h2>目录树</h2><p>{mappings.data?.items.filter((item) => item.enabled).map((item) => `${item.display_name} ${item.alist_path}`).join(" · ") || "尚未配置内容根目录"}</p></div><label className="small-search"><Search /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="筛选已索引目录" /></label></div>
        <div className="folder-tree">{filter ? filtered.map((item) => <button type="button" className={selectedId === item.id ? "filter-result selected" : "filter-result"} key={item.id} onClick={() => setSelectedId(item.id)}><Folder /><span><strong>{item.name}</strong><small>{item.path}</small></span></button>) : roots.length ? <ul>{roots.map((root) => <TreeNode key={root.id} node={root} childrenByParent={childrenByParent} expanded={expanded} selectedId={selectedId} toggle={toggle} select={setSelectedId} />)}</ul> : <div className="empty">暂无索引目录，请先配置映射并执行同步。</div>}</div>
      </article>
      <aside className="panel folder-detail-panel"><h2>目录详情</h2>{detail.data ? <dl><div><dt>名称</dt><dd>{detail.data.name}</dd></div><div><dt>真实路径</dt><dd>{detail.data.path}</dd></div><div><dt>内容类型</dt><dd>{typeNames[detail.data.content_type] ?? detail.data.content_type}</dd></div><div><dt>目录深度</dt><dd>{detail.data.depth}</dd></div><div><dt>子目录</dt><dd>{detail.data.child_folder_count}</dd></div><div><dt>直接资源</dt><dd>{detail.data.direct_resource_count}</dd></div><div><dt>最近修改</dt><dd>{detail.data.modified_at ? new Date(detail.data.modified_at).toLocaleString("zh-CN") : "上游未提供"}</dd></div><div><dt>索引状态</dt><dd className="ok-text">已激活</dd></div></dl> : <div className="empty compact">从左侧选择目录查看详情</div>}</aside>
    </section>

  </div></AdminShell>;
}
