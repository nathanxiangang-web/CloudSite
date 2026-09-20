"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BookOpen, Check, Eye, EyeOff, FolderKanban, Plus, Search, Trash2, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, Collection, formatBytes, SearchResponse } from "@/lib/api";
import { fetchCatalogEntries, fetchCatalogSearch } from "@/lib/catalog-client";
import type { CatalogEntrySummary } from "@/lib/catalog";
import { SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";

type AdminResourceItem = { item_type: "resource"; resource_id: string; name: string | null; content_type: string; extension: string; size: number; active: boolean; note: string; sort_order: number };
type AdminEntryItem = { item_type: "catalog_entry"; catalog_entry_id: string; title: string | null; content_type: string; status: string | null; active: boolean; note: string; sort_order: number };
type AdminCollectionItem = AdminResourceItem | AdminEntryItem;
type AdminCollectionDetail = { id: number; name: string; description: string; cover: string; status: "active" | "hidden"; visible_on_home: boolean; sort_order: number; goal: string; audience: string; prerequisites: string; item_intro: string; items: AdminCollectionItem[] };

const typeLabel: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "文件" };

export default function CollectionsPage() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibleOnHome, setVisibleOnHome] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);

  const collections = useQuery({ queryKey: ["admin-collections"], queryFn: () => api<{ items: Collection[] }>("/api/admin/collections") });
  const create = useMutation({
    mutationFn: () => api<{ id: number }>("/api/admin/collections", { method: "POST", body: JSON.stringify({ name, description, cover: "", status: "active", visible_on_home: visibleOnHome, sort_order: 0, goal: "", audience: "", prerequisites: "", item_intro: "" }) }),
    onSuccess: () => { setName(""); setDescription(""); setVisibleOnHome(true); client.invalidateQueries({ queryKey: ["admin-collections"] }); },
  });
  const remove = useMutation({ mutationFn: (id: number) => api(`/api/admin/collections/${id}`, { method: "DELETE" }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-collections"] }) });

  const submit = (event: FormEvent) => { event.preventDefault(); if (name.trim()) create.mutate(); };

  return <AdminShell title="精选合集"><div className="admin-page">
    <section className="panel collection-create"><div><h2><FolderKanban />创建合集</h2><p className="panel-intro">合集可以跨目录组织资源，并按需显示在首页。</p></div><form className="inline-form" onSubmit={submit}><input value={name} onChange={(e) => setName(e.target.value)} placeholder="合集名称" required /><input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句话说明" /><label className="check"><input type="checkbox" checked={visibleOnHome} onChange={(e) => setVisibleOnHome(e.target.checked)} />首页展示</label><button className="primary" disabled={create.isPending}><Plus />创建</button></form>{create.error && <p className="form-error">{create.error.message}</p>}</section>

    {editingId !== null ? <CollectionEditor id={editingId} onClose={() => setEditingId(null)} /> : null}

    <section className="collection-admin-grid">
      {collections.isLoading ? <div className="loading">正在加载合集…</div>
        : collections.error ? <div className="panel empty error-state">加载合集失败：{collections.error.message}<button type="button" onClick={() => collections.refetch()}>重试</button></div>
        : collections.data?.items.length ? collections.data.items.map((collection) => <article className="panel collection-admin-card" key={collection.id}>
          <div className="collection-admin-head"><span className="stat-icon purple"><FolderKanban /></span><div><h2>{collection.name}</h2><p>{collection.description || "暂无说明"}</p></div>{collection.status === "hidden" ? <EyeOff aria-label="已隐藏" /> : <Eye aria-label="公开" />}</div>
          <dl><div><dt>资源数</dt><dd>{collection.item_count}</dd></div><div><dt>状态</dt><dd>{collection.status === "hidden" ? "隐藏" : "公开"}</dd></div><div><dt>首页展示</dt><dd>{collection.visible_on_home ? "是" : "否"}</dd></div></dl>
          <div className="card-actions"><Link className="button" href={`/collections/${collection.id}`}>查看</Link><button onClick={() => setEditingId(collection.id)}>编辑</button><button className="danger" onClick={() => window.confirm(`删除合集“${collection.name}”？`) && remove.mutate(collection.id)}><Trash2 />删除</button></div>
        </article>) : <div className="panel empty">还没有合集，先创建一个。</div>}
    </section>
    {remove.error && <p className="form-error">{remove.error.message}</p>}
  </div></AdminShell>;
}

function CollectionEditor({ id, onClose }: { id: number; onClose: () => void }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["admin-collection", id], queryFn: () => api<AdminCollectionDetail>(`/api/admin/collections/${id}`) });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [cover, setCover] = useState("");
  const [status, setStatus] = useState<"active" | "hidden">("active");
  const [visibleOnHome, setVisibleOnHome] = useState(true);
  const [sortOrder, setSortOrder] = useState(0);
  const [goal, setGoal] = useState("");
  const [audience, setAudience] = useState("");
  const [prerequisites, setPrerequisites] = useState("");
  const [itemIntro, setItemIntro] = useState("");
  const [items, setItems] = useState<AdminCollectionItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");

  const [syncedData, setSyncedData] = useState(query.data);
  if (query.data !== syncedData) {
    setSyncedData(query.data);
    const data = query.data;
    if (data) {
      setName(data.name);
      setDescription(data.description);
      setCover(data.cover);
      setStatus(data.status);
      setVisibleOnHome(data.visible_on_home);
      setSortOrder(data.sort_order);
      setGoal(data.goal);
      setAudience(data.audience);
      setPrerequisites(data.prerequisites);
      setItemIntro(data.item_intro);
      setItems(data.items);
    }
  }

  const search = useQuery({ queryKey: ["collection-picker", searchQuery], queryFn: () => api<SearchResponse>(`/api/search?q=${encodeURIComponent(searchQuery)}&object_type=resource&page_size=20`), enabled: searchQuery.trim().length > 0 });
  const catalogSearch = useQuery({
    queryKey: ["collection-catalog-picker", catalogQuery],
    queryFn: () => catalogQuery.trim()
      ? fetchCatalogSearch({ q: catalogQuery.trim(), page_size: 20 })
      : fetchCatalogEntries({ page_size: 20 }),
  });
  const save = useMutation({ mutationFn: () => api(`/api/admin/collections/${id}`, { method: "PUT", body: JSON.stringify({ name, description, cover, status, visible_on_home: visibleOnHome, sort_order: sortOrder, goal, audience, prerequisites, item_intro: itemIntro }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-collections"] }) });
  const saveItems = useMutation({ mutationFn: (next: AdminCollectionItem[]) => api(`/api/admin/collections/${id}/items`, { method: "PUT", body: JSON.stringify({ items: next.map((i) => i.item_type === "resource" ? { item_type: "resource", resource_id: i.resource_id, catalog_entry_id: null, note: i.note } : { item_type: "catalog_entry", resource_id: null, catalog_entry_id: i.catalog_entry_id, note: i.note }) }) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-collections"] }); client.invalidateQueries({ queryKey: ["admin-collection", id] }); } });

  const addResource = (resourceId: string, label: string, contentType: string, extension: string, size: number) => { if (!items.some((i) => i.item_type === "resource" && i.resource_id === resourceId)) setItems([...items, { item_type: "resource", resource_id: resourceId, name: label, content_type: contentType, extension, size, active: true, note: "", sort_order: items.length }]); };
  const addCatalogEntry = (entry: CatalogEntrySummary) => { if (!items.some((i) => i.item_type === "catalog_entry" && i.catalog_entry_id === entry.entry_id)) setItems([...items, { item_type: "catalog_entry", catalog_entry_id: entry.entry_id, title: entry.title, content_type: entry.content_type, status: entry.status, active: entry.status === "published", note: "", sort_order: items.length }]); };
  const removeItem = (index: number) => setItems(items.filter((_, i) => i !== index));
  const moveItem = (index: number, dir: -1 | 1) => { const next = [...items]; const target = index + dir; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; setItems(next); };
  const setItemNote = (index: number, note: string) => setItems(items.map((it, i) => i === index ? { ...it, note } : it));
  const persistAll = () => { save.mutate(); saveItems.mutate(items); };

  if (query.isLoading) return <div className="panel loading">正在加载合集…</div>;
  if (query.error) return <div className="panel empty error-state">加载合集详情失败：{query.error.message}<div className="card-actions"><button type="button" onClick={() => query.refetch()}>重试</button><button type="button" onClick={onClose}><X />关闭</button></div></div>;
  if (!query.data) return null;

  const addedResourceIds = new Set(items.filter((i): i is AdminResourceItem => i.item_type === "resource").map((i) => i.resource_id));
  const addedEntryIds = new Set(items.filter((i): i is AdminEntryItem => i.item_type === "catalog_entry").map((i) => i.catalog_entry_id));
  const catalogResults = catalogSearch.data?.items ?? [];

  return <section className="panel collection-editor">
    <div className="panel-toolbar"><div><h2>编辑合集 #{id}</h2><p>修改合集信息并管理其中的资源与教程条目。</p></div><button onClick={onClose}><X />关闭</button></div>
    <div className="form-stack">
      <label>合集名称<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>简介<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} /></label>
      <label>目标<textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={2} placeholder="这个专题要达成什么目标" /></label>
      <div className="collection-editor-row"><label>对象<input value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="面向谁" /></label><label>排序值<input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} /></label></div>
      <label>准备条件<textarea value={prerequisites} onChange={(e) => setPrerequisites(e.target.value)} rows={2} placeholder="开始前需要具备的条件" /></label>
      <label>条目说明<textarea value={itemIntro} onChange={(e) => setItemIntro(e.target.value)} rows={2} placeholder="对条目的总体说明" /></label>
      <label>封面资源 ID（留空使用默认封面，可填图片资源 ID）<input value={cover} onChange={(e) => setCover(e.target.value)} placeholder="图片资源 ID" /></label>
      <div className="collection-editor-row"><label>状态<select value={status} onChange={(e) => setStatus(e.target.value as "active" | "hidden")}><option value="active">公开</option><option value="hidden">隐藏</option></select></label><label className="check"><input type="checkbox" checked={visibleOnHome} onChange={(e) => setVisibleOnHome(e.target.checked)} />首页展示</label></div>
    </div>

    <h3>合集条目（{items.length} 个）</h3>
    <div className="picker-items">{items.map((item, index) => <div className="picker-item" key={item.item_type === "resource" ? `r-${item.resource_id}` : `c-${item.catalog_entry_id}`}>
      <span className={`picker-item-icon type-${item.content_type || "file"}`}>{item.item_type === "catalog_entry" ? <BookOpen /> : <FolderKanban />}</span>
      <span className="picker-item-copy">
        <strong>{item.item_type === "resource" ? (item.name ?? item.resource_id) : (item.title ?? item.catalog_entry_id)}</strong>
        <small>{item.item_type === "resource" ? `${typeLabel[item.content_type] ?? item.content_type}${item.extension ? ` · ${item.extension.toUpperCase()}` : ""}${item.size ? ` · ${formatBytes(item.size)}` : ""}${item.active ? "" : "（已失效）"}` : `教程 · ${typeLabel[item.content_type] ?? item.content_type}${item.active ? "" : "（未发布）"}`}</small>
        <input className="picker-item-note" value={item.note} onChange={(e) => setItemNote(index, e.target.value)} placeholder="该条目说明（可选）" />
      </span>
      <button onClick={() => moveItem(index, -1)} disabled={index === 0}><ArrowUp /></button>
      <button onClick={() => moveItem(index, 1)} disabled={index === items.length - 1}><ArrowDown /></button>
      <button className="danger" onClick={() => removeItem(index)}><Trash2 /></button>
    </div>)}</div>

    <h3>添加资源</h3>
    <div className="small-search"><Search /><input maxLength={SEARCH_QUERY_MAX_LENGTH} value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索资源名称或类型，如 Chrome / pdf / 摄影" /></div>
    <div className="picker-results">{search.isLoading ? <div className="loading">搜索中…</div> : search.error ? <div className="empty error-state">资源搜索失败：{search.error.message}<button type="button" onClick={() => search.refetch()}>重试</button></div> : search.data?.items.filter((r) => r.object_type === "resource").map((resource) => { const added = addedResourceIds.has(resource.id); return <div className="picker-item" key={resource.id}><span className={`picker-item-icon type-${resource.content_type || "file"}`}><FolderKanban /></span><span className="picker-item-copy"><strong>{resource.name}</strong><small>{typeLabel[resource.content_type] ?? resource.content_type}{resource.extension ? ` · ${resource.extension.toUpperCase()}` : ""}{resource.size != null ? ` · ${formatBytes(resource.size)}` : ""}</small></span>{added ? <button disabled><Check />已添加</button> : <button className="primary" onClick={() => addResource(resource.id, resource.name, resource.content_type, resource.extension, resource.size ?? 0)}><Plus />添加</button>}</div>; })}</div>

    <h3>添加教程条目（Catalog）</h3>
    <div className="small-search"><BookOpen /><input value={catalogQuery} onChange={(e) => setCatalogQuery(e.target.value)} placeholder="按标题筛选已发布的 Catalog 条目" /></div>
    <div className="picker-results">{catalogSearch.isLoading ? <div className="loading">加载中…</div> : catalogSearch.error ? <div className="empty error-state">Catalog 加载失败：{catalogSearch.error.message}<button type="button" onClick={() => catalogSearch.refetch()}>重试</button></div> : catalogResults.map((entry) => { const added = addedEntryIds.has(entry.entry_id); return <div className="picker-item" key={entry.entry_id}><span className={`picker-item-icon type-${entry.content_type || "file"}`}><BookOpen /></span><span className="picker-item-copy"><strong>{entry.title}</strong><small>{typeLabel[entry.content_type] ?? entry.content_type}{entry.summary ? ` · ${entry.summary}` : ""}</small></span>{added ? <button disabled><Check />已添加</button> : <button className="primary" onClick={() => addCatalogEntry(entry)}><Plus />添加</button>}</div>; })}</div>

    <div className="form-actions"><button onClick={onClose}>取消</button><button className="primary" onClick={persistAll} disabled={save.isPending || saveItems.isPending}>保存</button></div>
    {(save.error || saveItems.error) && <p className="form-error">{(save.error ?? saveItems.error)?.message}</p>}
  </section>;
}
