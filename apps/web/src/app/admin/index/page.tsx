"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Clock3, Database, File, Folder, RefreshCw, RotateCcw, Search } from "lucide-react";
import { useMemo, useState } from "react";
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
};
type IndexSummary = { folders: number; resources: number; syncing: boolean; latest_sync: SyncRun | null };
type Mapping = { id: number; content_type: string; display_name: string; alist_path: string; enabled: boolean };
type Change = { id: number; object_type: string; change_type: string; old_path: string | null; new_path: string | null; created_at: string };
type RollingStatus = {
  engine_version: string;
  mode: string;
  migrated_at?: string | null;
  cycle: null | {
    id: number;
    type: string;
    status: string;
    anchor_at: string;
    windows_total: number;
    windows_completed: number;
    next_window_at: string;
    planned_folder_count: number;
    completed_folder_count: number;
    failed_folder_count: number;
    remaining_folder_count: number;
    next_window_target: number;
    alist_list_requests: number;
    window_list_requests: number;
    changed_scope_count: number;
    unchanged_scope_count: number;
  };
};

const typeNames: Record<string, string> = { software: "软件", image: "图片", video: "视频", document: "文档", file: "普通文件" };

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
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const summary = useQuery({ queryKey: ["index-summary"], queryFn: () => api<IndexSummary>("/api/admin/index/summary"), refetchInterval: (query) => query.state.data?.syncing ? 2000 : false });
  const folders = useQuery({ queryKey: ["admin-folders"], queryFn: () => api<{ items: FolderType[] }>("/api/admin/index/folders") });
  const mappings = useQuery({ queryKey: ["mappings"], queryFn: () => api<{ items: Mapping[] }>("/api/admin/root-mappings") });
  const runs = useQuery({ queryKey: ["sync-runs"], queryFn: () => api<{ items: SyncRun[] }>("/api/admin/sync-runs?limit=8") });
  const rolling = useQuery({ queryKey: ["rolling-status"], queryFn: () => api<RollingStatus>("/api/admin/sync/status"), refetchInterval: 5000 });
  const detail = useQuery({ queryKey: ["admin-folder", selectedId], queryFn: () => api<FolderType & { direct_resource_count: number }>(`/api/admin/index/folders/${selectedId}`), enabled: Boolean(selectedId) });
  const changes = useQuery({ queryKey: ["sync-changes", selectedRunId], queryFn: () => api<{ items: Change[] }>(`/api/admin/sync-runs/${selectedRunId}/changes?limit=50`), enabled: Boolean(selectedRunId) });
  const refresh = () => { client.invalidateQueries({ queryKey: ["index-summary"] }); client.invalidateQueries({ queryKey: ["admin-folders"] }); client.invalidateQueries({ queryKey: ["sync-runs"] }); client.invalidateQueries({ queryKey: ["rolling-status"] }); };
  const sync = useMutation({ mutationFn: (full: boolean) => rolling.data?.engine_version === "1.1" ? api("/api/admin/sync/window/run", { method: "POST" }) : api("/api/admin/sync", { method: "POST", body: JSON.stringify({ full }) }), onSuccess: refresh });

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
  const rollingCycle = rolling.data?.cycle;
  const isRolling = rolling.data?.engine_version === "1.1";
  const busy = sync.isPending || summary.data?.syncing;
  const toggle = (id: string) => setExpanded((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });

  return <AdminShell title="内容索引"><div className="admin-page index-admin-page">
    <section className="index-summary-grid"><article><Database /><span><small>索引资源</small><strong>{summary.data?.resources ?? 0}</strong></span></article><article><Folder /><span><small>目录数量</small><strong>{summary.data?.folders ?? 0}</strong></span></article><article><Clock3 /><span><small>最近同步</small><strong>{latest?.status === "success" ? "已完成" : latest?.status === "failed" ? "失败" : latest?.status === "running" ? "进行中" : "未运行"}</strong></span></article></section>
    <section className="panel index-control-panel"><div><h2>{isRolling ? "滚动全量校验" : "动态索引"}</h2><p>{isRolling ? "首次索引已保留；系统在 24 小时内分 4 个窗口完成一次目录覆盖。" : "目录和资源完全来自已启用的 AList 根目录映射。"}</p></div><div className="index-actions"><button type="button" className={isRolling ? "primary" : ""} disabled={busy} onClick={() => sync.mutate(false)}><RefreshCw className={busy ? "spin" : ""} />{isRolling ? "开始当前窗口" : "立即同步"}</button>{!isRolling && <button type="button" className="primary" disabled={busy} onClick={() => sync.mutate(true)}><RotateCcw />完整重建</button>}</div>{sync.error && <p className="form-error">{sync.error.message}</p>}</section>
    {isRolling && rollingCycle && <section className="panel sync-history-panel"><div className="panel-toolbar"><div><h2>Rolling Cycle #{rollingCycle.id}</h2><p>当前窗口 {Math.min(rollingCycle.windows_completed + 1, rollingCycle.windows_total)} / {rollingCycle.windows_total} · 下一窗口目标 {rollingCycle.next_window_target} 个目录 · 下次计划 {new Date(rollingCycle.next_window_at).toLocaleString("zh-CN")}</p></div><b className={`sync-status ${rollingCycle.status}`}>{rollingCycle.status}</b></div><section className="index-summary-grid"><article><Folder /><span><small>本轮完成</small><strong>{rollingCycle.completed_folder_count} / {rollingCycle.planned_folder_count}</strong></span></article><article><Clock3 /><span><small>剩余目录</small><strong>{rollingCycle.remaining_folder_count}</strong></span></article><article><RefreshCw /><span><small>本轮 List 请求</small><strong>{rollingCycle.window_list_requests}</strong><small className="sub-note">Cycle 累计 {rollingCycle.alist_list_requests}</small></span></article></section></section>}
    <section className="index-workspace"><article className="panel folder-tree-panel"><div className="panel-toolbar"><div><h2>Folder Tree</h2><p>{mappings.data?.items.filter((item) => item.enabled).map((item) => `${item.display_name} ${item.alist_path}`).join(" · ") || "尚未配置内容根目录"}</p></div><label className="small-search"><Search /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="筛选已索引目录" /></label></div>
      <div className="folder-tree">{filter ? filtered.map((item) => <button type="button" className={selectedId === item.id ? "filter-result selected" : "filter-result"} key={item.id} onClick={() => setSelectedId(item.id)}><Folder /><span><strong>{item.name}</strong><small>{item.path}</small></span></button>) : roots.length ? <ul>{roots.map((root) => <TreeNode key={root.id} node={root} childrenByParent={childrenByParent} expanded={expanded} selectedId={selectedId} toggle={toggle} select={setSelectedId} />)}</ul> : <div className="empty">暂无索引目录，请先配置映射并执行同步。</div>}</div>
    </article><aside className="panel folder-detail-panel"><h2>目录详情</h2>{detail.data ? <dl><div><dt>名称</dt><dd>{detail.data.name}</dd></div><div><dt>真实路径</dt><dd>{detail.data.path}</dd></div><div><dt>内容类型</dt><dd>{typeNames[detail.data.content_type] ?? detail.data.content_type}</dd></div><div><dt>目录深度</dt><dd>{detail.data.depth}</dd></div><div><dt>子目录</dt><dd>{detail.data.child_folder_count}</dd></div><div><dt>直接资源</dt><dd>{detail.data.direct_resource_count}</dd></div><div><dt>最近修改</dt><dd>{detail.data.modified_at ? new Date(detail.data.modified_at).toLocaleString("zh-CN") : "上游未提供"}</dd></div><div><dt>索引状态</dt><dd className="ok-text">active</dd></div></dl> : <div className="empty compact">从左侧选择目录查看详情</div>}</aside></section>
    <section className="panel sync-history-panel"><div className="panel-toolbar"><div><h2>同步记录与变化</h2><p>选择一次同步查看新增、修改和移除的索引对象。</p></div></div><div className="sync-history-layout"><div className="sync-run-list">{runs.data?.items.map((run) => <button type="button" className={selectedRunId === run.id ? "selected" : ""} key={run.id} onClick={() => setSelectedRunId(run.id)}><span><strong>#{run.id} · {run.sync_type}</strong><small>{new Date(run.started_at).toLocaleString("zh-CN")} · {(run.duration_ms / 1000).toFixed(1)} 秒</small></span><b className={`sync-status ${run.status}`}>{run.status}</b><em>+{run.added_count} / ~{run.updated_count} / -{run.removed_count}</em></button>)}</div><div className="sync-change-list">{selectedRunId ? changes.isLoading ? <div className="empty compact">正在读取变化…</div> : changes.data?.items.length ? changes.data.items.map((change) => <div key={change.id}><span className={`change-type ${change.change_type}`}>{change.change_type}</span>{change.object_type === "folder" ? <Folder /> : <File />}<p>{change.new_path || change.old_path}</p></div>) : <div className="empty compact">本次同步没有索引变化</div> : <div className="empty compact">选择左侧同步记录</div>}</div></div></section>
  </div></AdminShell>;
}
