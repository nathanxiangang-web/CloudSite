"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Check, Eye, EyeOff, FolderKanban, Plus, Search, Trash2, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, Collection, formatBytes, SearchResponse } from "@/lib/api";

type AdminCollectionItem = { resource_id: string; name: string | null; content_type: string; extension: string; size: number; active: boolean };
type AdminCollectionDetail = { id: number; name: string; description: string; cover: string; status: "active" | "hidden"; visible_on_home: boolean; sort_order: number; items: AdminCollectionItem[] };

const typeLabel: Record<string, string> = { software: "软件", image: "图片", video: "视频", document: "文档", file: "文件" };

export default function CollectionsPage() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibleOnHome, setVisibleOnHome] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);

  const collections = useQuery({ queryKey: ["admin-collections"], queryFn: () => api<{ items: Collection[] }>("/api/admin/collections") });
  const create = useMutation({
    mutationFn: () => api<{ id: number }>("/api/admin/collections", { method: "POST", body: JSON.stringify({ name, description, cover: "", status: "active", visible_on_home: visibleOnHome, sort_order: 0 }) }),
    onSuccess: () => { setName(""); setDescription(""); setVisibleOnHome(true); client.invalidateQueries({ queryKey: ["admin-collections"] }); },
  });
  const remove = useMutation({ mutationFn: (id: number) => api(`/api/admin/collections/${id}`, { method: "DELETE" }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-collections"] }) });

  const submit = (event: FormEvent) => { event.preventDefault(); if (name.trim()) create.mutate(); };

  return <AdminShell title="精选合集"><div className="admin-page">
    <section className="panel collection-create"><div><h2><FolderKanban />创建合集</h2><p className="panel-intro">合集可以跨目录组织资源，并按需显示在首页。</p></div><form className="inline-form" onSubmit={submit}><input value={name} onChange={(e) => setName(e.target.value)} placeholder="合集名称" required /><input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句话说明" /><label className="check"><input type="checkbox" checked={visibleOnHome} onChange={(e) => setVisibleOnHome(e.target.checked)} />首页展示</label><button className="primary" disabled={create.isPending}><Plus />创建</button></form>{create.error && <p className="form-error">{create.error.message}</p>}</section>

    {editingId !== null ? <CollectionEditor id={editingId} onClose={() => setEditingId(null)} /> : null}

    <section className="collection-admin-grid">
      {collections.isLoading ? <div className="loading">正在加载合集…</div>
        : collections.data?.items.length ? collections.data.items.map((collection) => <article className="panel collection-admin-card" key={collection.id}>
          <div className="collection-admin-head"><span className="stat-icon purple"><FolderKanban /></span><div><h2>{collection.name}</h2><p>{collection.description || "暂无说明"}</p></div>{collection.status === "hidden" ? <EyeOff aria-label="已隐藏" /> : <Eye aria-label="公开" />}</div>
          <dl><div><dt>资源数</dt><dd>{collection.item_count}</dd></div><div><dt>状态</dt><dd>{collection.status === "hidden" ? "隐藏" : "公开"}</dd></div><div><dt>首页展示</dt><dd>{collection.visible_on_home ? "是" : "否"}</dd></div></dl>
          <div className="card-actions"><Link className="button" href={`/collections/${collection.id}`}>查看</Link><button onClick={() => setEditingId(collection.id)}>编辑</button><button className="danger" onClick={() => window.confirm(`删除合集“${collection.name}”？`) && remove.mutate(collection.id)}><Trash2 />删除</button></div>
        </article>) : <div className="panel empty">还没有合集，先创建一个。</div>}
    </section>
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
  const [itemIds, setItemIds] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    const data = query.data;
    if (!data) return;
    setName(data.name);
    setDescription(data.description);
    setCover(data.cover);
    setStatus(data.status);
    setVisibleOnHome(data.visible_on_home);
    setSortOrder(data.sort_order);
    setItemIds(data.items.map((i) => i.resource_id));
  }, [query.data]);

  const search = useQuery({ queryKey: ["collection-picker", searchQuery], queryFn: () => api<SearchResponse>(`/api/search?q=${encodeURIComponent(searchQuery)}&object_type=resource&page_size=20`), enabled: searchQuery.trim().length > 0 });
  const save = useMutation({ mutationFn: () => api(`/api/admin/collections/${id}`, { method: "PUT", body: JSON.stringify({ name, description, cover, status, visible_on_home: visibleOnHome, sort_order: sortOrder }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["admin-collections"] }) });
  const saveItems = useMutation({ mutationFn: (ids: string[]) => api(`/api/admin/collections/${id}/items`, { method: "PUT", body: JSON.stringify({ resource_ids: ids }) }), onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-collections"] }); client.invalidateQueries({ queryKey: ["admin-collection", id] }); } });

  const addItem = (resourceId: string) => { if (!itemIds.includes(resourceId)) setItemIds([...itemIds, resourceId]); };
  const removeItem = (resourceId: string) => setItemIds(itemIds.filter((x) => x !== resourceId));
  const moveItem = (index: number, dir: -1 | 1) => { const next = [...itemIds]; const target = index + dir; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; setItemIds(next); };
  const persistAll = () => { save.mutate(); saveItems.mutate(itemIds); };

  if (query.isLoading) return <div className="panel loading">正在加载合集…</div>;

  const addedIds = new Set(itemIds);
  const missingCount = (query.data?.items ?? []).filter((i) => !i.active).length;

  return <section className="panel collection-editor">
    <div className="panel-toolbar"><div><h2>编辑合集 #{id}</h2><p>修改合集信息并管理其中的资源。</p></div><button onClick={onClose}><X />关闭</button></div>
    <div className="form-stack">
      <label>合集名称<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>简介<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} /></label>
      <label>封面资源 ID（留空使用默认封面，可填图片资源 ID）<input value={cover} onChange={(e) => setCover(e.target.value)} placeholder="图片资源 ID" /></label>
      <div className="collection-editor-row"><label>状态<select value={status} onChange={(e) => setStatus(e.target.value as "active" | "hidden")}><option value="active">公开</option><option value="hidden">隐藏</option></select></label><label>排序值<input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} /></label><label className="check"><input type="checkbox" checked={visibleOnHome} onChange={(e) => setVisibleOnHome(e.target.checked)} />首页展示</label></div>
    </div>

    <h3>合集资源（{itemIds.length} 个{missingCount ? `，${missingCount} 个已失效` : ""}）</h3>
    <div className="picker-items">{itemIds.map((resourceId, index) => { const item = query.data?.items.find((i) => i.resource_id === resourceId); const label = item?.name ?? resourceId; const missing = item?.active === false; return <div className="picker-item" key={resourceId}><span className={`picker-item-icon ${missing ? "missing" : `type-${item?.content_type || "file"}`}`}><FolderKanban /></span><span className="picker-item-copy"><strong>{missing ? `${label}（已失效）` : label}</strong>{!missing && item && <small>{typeLabel[item.content_type] ?? item.content_type}{item.extension ? ` · ${item.extension.toUpperCase()}` : ""}{item.size ? ` · ${formatBytes(item.size)}` : ""}</small>}</span><button onClick={() => moveItem(index, -1)} disabled={index === 0}><ArrowUp /></button><button onClick={() => moveItem(index, 1)} disabled={index === itemIds.length - 1}><ArrowDown /></button><button className="danger" onClick={() => removeItem(resourceId)}><Trash2 /></button></div>; })}</div>

    <h3>添加资源</h3>
    <div className="small-search"><Search /><input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索资源名称或类型，如 Chrome / pdf / 摄影" /></div>
    <div className="picker-results">{search.isLoading ? <div className="loading">搜索中…</div> : search.data?.items.filter((r) => r.object_type === "resource").map((resource) => { const added = addedIds.has(resource.id); return <div className="picker-item" key={resource.id}><span className={`picker-item-icon type-${resource.content_type || "file"}`}><FolderKanban /></span><span className="picker-item-copy"><strong>{resource.name}</strong><small>{typeLabel[resource.content_type] ?? resource.content_type}{resource.extension ? ` · ${resource.extension.toUpperCase()}` : ""}{resource.size != null ? ` · ${formatBytes(resource.size)}` : ""}</small></span>{added ? <button disabled><Check />已添加</button> : <button className="primary" onClick={() => addItem(resource.id)}><Plus />添加</button>}</div>; })}</div>

    <div className="form-actions"><button onClick={onClose}>取消</button><button className="primary" onClick={persistAll} disabled={save.isPending || saveItems.isPending}>保存</button></div>
    {(save.error || saveItems.error) && <p className="form-error">{(save.error ?? saveItems.error)?.message}</p>}
  </section>;
}
