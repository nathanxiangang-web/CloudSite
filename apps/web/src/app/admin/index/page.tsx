"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Database, Folder, RefreshCw, Search, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { progressStyles } from "@/features/admin-index";
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
  directories_done?: number;
  known_pending?: number;
  active_workers?: number;
  entries_discovered?: number;
  recent_paths?: string[];
};
type IndexSummary = { folders: number; resources: number; syncing: boolean; latest_sync: SyncRun | null };
type SyncProgress = {
  engine_version: string;
  status: string;
  roots_completed: number;
  roots_total: number;
  categories_done: number;
  elapsed_seconds: number;
  active_workers: number;
  directories_done: number;
  known_pending: number;
  entries_discovered: number;
  recent_paths: string[];
  current_path: string;
};
type Mapping = { id: number; content_type: string; display_name: string; alist_path: string; enabled: boolean };

const typeNames: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "普通文件" };
const runStatusLabel: Record<string, string> = { success: "已完成", completed: "已完成", failed: "失败", running: "进行中", pending: "等待中", partial: "部分完成", cancelled: "已取消", skipped: "已跳过" };
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
  const summary = useQuery({ queryKey: ["index-summary"], queryFn: () => api<IndexSummary>("/api/admin/index/summary"), refetchInterval: 2000 });
  const progress = useQuery({ queryKey: ["sync-progress"], queryFn: () => api<SyncProgress>("/api/admin/sync/status"), refetchInterval: 1000 });
  const folders = useQuery({ queryKey: ["admin-folders"], queryFn: () => api<{ items: FolderType[] }>("/api/admin/index/folders") });
  const mappings = useQuery({ queryKey: ["mappings"], queryFn: () => api<{ items: Mapping[] }>("/api/admin/root-mappings") });
  const detail = useQuery({ queryKey: ["admin-folder", selectedId], queryFn: () => api<FolderType & { direct_resource_count: number }>(`/api/admin/index/folders/${selectedId}`), enabled: Boolean(selectedId) });
  const refresh = () => { client.invalidateQueries({ queryKey: ["index-summary"] }); client.invalidateQueries({ queryKey: ["sync-progress"] }); client.invalidateQueries({ queryKey: ["admin-folders"] }); client.invalidateQueries({ queryKey: ["admin-folder"] }); };
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
  const syncing = progress.data?.status === "running" || (summary.data?.syncing ?? false);
  const rootsCompleted = progress.data?.roots_completed ?? latest?.roots_completed ?? 0;
  const rootsTotal = progress.data?.roots_total ?? latest?.roots_total ?? 0;
  const directoriesDone = progress.data?.directories_done ?? latest?.directories_done ?? latest?.folders_scanned ?? 0;
  const knownPending = progress.data?.known_pending ?? latest?.known_pending ?? 0;
  const activeWorkers = progress.data?.active_workers ?? latest?.active_workers ?? 0;
  const entriesDiscovered = progress.data?.entries_discovered ?? latest?.entries_discovered ?? latest?.resources_scanned ?? 0;
  const currentPath = progress.data?.current_path || latest?.current_path || "";
  const elapsedSeconds = progress.data?.elapsed_seconds ?? Math.round((latest?.duration_ms ?? 0) / 1000);
  const rootProgressPercent = rootsTotal > 0 ? Math.min(100, Math.max(0, (rootsCompleted / rootsTotal) * 100)) : 0;
  const summaryLoading = summary.isLoading && !summary.data;
  const summaryUnavailable = Boolean(summary.error) && !summary.data;
  const resourceCountText = summary.data ? String(summary.data.resources) : summaryLoading ? "…" : "不可用";
  const folderCountText = summary.data ? String(summary.data.folders) : summaryLoading ? "…" : "不可用";
  const enabledMappings = mappings.data?.items.filter((item) => item.enabled) ?? [];
  const noEnabledMappings = Boolean(mappings.data) && enabledMappings.length === 0;
  const toggle = (id: string) => setExpanded((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });

  const syncStatusIcon = summaryLoading ? <Loader2 className="spin" /> : summaryUnavailable ? <AlertTriangle className="warn" /> : syncing ? <Loader2 className="spin" /> : latest?.status === "success" ? <CheckCircle2 className="ok" /> : latest?.status === "failed" ? <AlertTriangle className="warn" /> : <Database />;
  const syncStatusText = summaryLoading ? "读取中" : summaryUnavailable ? "不可用" : syncing ? "进行中" : latest ? labelOf(runStatusLabel, latest.status) : "未运行";
  const syncDetail = summaryUnavailable ? "索引摘要请求失败" : latest?.status === "failed" && latest.error_message ? latest.error_message : latest && !syncing ? `${latest.added_count > 0 ? `+${latest.added_count} ` : ""}${latest.updated_count > 0 ? `~${latest.updated_count} ` : ""}${latest.removed_count > 0 ? `-${latest.removed_count}` : ""}${latest.added_count + latest.updated_count + latest.removed_count === 0 ? "无变化" : ""} · ${(latest.duration_ms / 1000).toFixed(1)}s` : syncing ? `${rootsCompleted} / ${rootsTotal || "?"} 根目录 · ${directoriesDone} 目录 · ${entriesDiscovered} 条目 · ${elapsedSeconds}s` : "";

  return <AdminShell title="内容索引"><div className="admin-page index-admin-page">
    {summary.error && <p className="form-error">索引摘要加载失败：{summary.error.message} <button type="button" onClick={() => summary.refetch()}>重试</button></p>}
    <section className="index-summary-grid">
      <article><Database /><span><small>索引资源</small><strong>{resourceCountText}</strong></span></article>
      <article><Folder /><span><small>目录数量</small><strong>{folderCountText}</strong></span></article>
      <article>{syncStatusIcon}<span><small>最近同步</small><strong>{syncStatusText}</strong><small>{syncDetail}</small></span></article>
    </section>
    <section className="panel index-control-panel">
      <div className="index-control-info"><h2>Indexing v2</h2><p>扫描 AList 目录并同步到索引数据库</p></div>
      <div className="index-actions">
        {noEnabledMappings
          ? <Link className="button primary" href="/admin/system">先配置内容根目录</Link>
          : syncing
            ? <button type="button" className="danger" disabled={cancelSync.isPending} onClick={() => cancelSync.mutate()}><AlertTriangle />取消同步</button>
            : <button type="button" className="primary" disabled={sync.isPending || mappings.isLoading || Boolean(mappings.error)} onClick={() => sync.mutate(false)}><RefreshCw />立即同步</button>}
      </div>
      {(sync.error || cancelSync.error) && <p className="form-error">{(sync.error || cancelSync.error)?.message}</p>}
      {syncing && <div className={progressStyles.progressBar}>
        <div className={progressStyles.progressHead}>
          <span className={progressStyles.currentPath}><Loader2 className="spin" />{currentPath ? `扫描中：${currentPath}` : rootsTotal > 0 ? "正在进入根目录…" : "正在读取 Provider 根目录…"}</span>
          <span>{elapsedSeconds}s</span>
        </div>
        <div className={progressStyles.liveMetrics}>
          <span><strong>{rootsCompleted} / {rootsTotal || "?"}</strong><small>根目录</small></span>
          <span><strong>{directoriesDone}</strong><small>当前 Root 已完成目录</small></span>
          <span><strong>{knownPending}</strong><small>当前 Root 待处理</small></span>
          <span><strong>{activeWorkers}</strong><small>活跃 Worker</small></span>
          <span><strong>{entriesDiscovered}</strong><small>已发现条目</small></span>
        </div>
        <div className={rootsTotal > 0 ? progressStyles.progressTrack : `${progressStyles.progressTrack} ${progressStyles.indeterminate}`} aria-label="同步活动进度">
          <i style={rootsTotal > 0 ? { width: `${rootProgressPercent}%` } : undefined} />
        </div>
        <p className={progressStyles.progressNote}>目录总量会在遍历过程中动态增长，因此不显示虚假的目录完成百分比；上方数值会实时更新。</p>
      </div>}
    </section>
    <section className="index-workspace">
      <article className="panel folder-tree-panel">
        <div className="panel-toolbar"><div><h2>目录树</h2><p>{mappings.isLoading ? "正在读取内容根目录…" : mappings.error ? `根目录配置读取失败：${mappings.error.message}` : mappings.data?.items.filter((item) => item.enabled).map((item) => `${item.display_name} ${item.alist_path}`).join(" · ") || "尚未配置内容根目录"}</p></div><label className="small-search"><Search /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="筛选已索引目录" /></label></div>
        <div className="folder-tree">{folders.isLoading ? <div className="loading">正在读取目录树…</div> : folders.error ? <div className="empty error-state">目录树加载失败：{folders.error.message}<button type="button" onClick={() => folders.refetch()}>重试</button></div> : filter ? filtered.map((item) => <button type="button" className={selectedId === item.id ? "filter-result selected" : "filter-result"} key={item.id} onClick={() => setSelectedId(item.id)}><Folder /><span><strong>{item.name}</strong><small>{item.path}</small></span></button>) : roots.length ? <ul>{roots.map((root) => <TreeNode key={root.id} node={root} childrenByParent={childrenByParent} expanded={expanded} selectedId={selectedId} toggle={toggle} select={setSelectedId} />)}</ul> : <div className="empty">暂无索引目录，请先配置映射并执行同步。</div>}</div>
      </article>
      <aside className="panel folder-detail-panel"><h2>目录详情</h2>{!selectedId ? <div className="empty compact">从左侧选择目录查看详情</div> : detail.isLoading ? <div className="loading">正在读取目录详情…</div> : detail.error ? <div className="empty error-state">目录详情加载失败：{detail.error.message}<button type="button" onClick={() => detail.refetch()}>重试</button></div> : detail.data ? <dl><div><dt>名称</dt><dd>{detail.data.name}</dd></div><div><dt>真实路径</dt><dd>{detail.data.path}</dd></div><div><dt>内容类型</dt><dd>{typeNames[detail.data.content_type] ?? detail.data.content_type}</dd></div><div><dt>目录深度</dt><dd>{detail.data.depth}</dd></div><div><dt>子目录</dt><dd>{detail.data.child_folder_count}</dd></div><div><dt>直接资源</dt><dd>{detail.data.direct_resource_count}</dd></div><div><dt>最近修改</dt><dd>{detail.data.modified_at ? new Date(detail.data.modified_at).toLocaleString("zh-CN") : "上游未提供"}</dd></div><div><dt>索引状态</dt><dd>已索引</dd></div></dl> : null}</aside>
    </section>

  </div></AdminShell>;
}
