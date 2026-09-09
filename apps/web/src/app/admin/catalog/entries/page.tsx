"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";
import {
  contentTypeLabel,
  statusLabel,
  type CatalogStatus,
} from "@/lib/catalog";
import { createAdminCatalogEntry, fetchAdminCatalogEntries } from "@/lib/catalog-client";

const CONTENT_TYPES = ["software", "image", "video", "document", "file"];

export default function AdminCatalogEntriesPage() {
  const client = useQueryClient();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [contentType, setContentType] = useState("software");
  const [summary, setSummary] = useState("");
  const [filter, setFilter] = useState("");

  const entries = useQuery({ queryKey: ["admin-catalog-entries"], queryFn: fetchAdminCatalogEntries });
  const create = useMutation({
    mutationFn: () => createAdminCatalogEntry({ content_type: contentType, title: title.trim(), summary: summary.trim(), status: "draft" }),
    onSuccess: (data) => { setTitle(""); setSummary(""); client.invalidateQueries({ queryKey: ["admin-catalog-entries"] }); router.push(`/admin/catalog/entries/${data.entry_id}`); },
  });

  const submit = (event: FormEvent) => { event.preventDefault(); if (title.trim()) create.mutate(); };
  const items = entries.data?.items ?? [];
  const visible = filter.trim() ? items.filter((entry) => entry.title.toLowerCase().includes(filter.trim().toLowerCase()) || entry.slug.includes(filter.trim().toLowerCase())) : items;

  return <AdminShell title="目录条目"><div className="admin-page">
    <section className="panel collection-create">
      <div><h2><Boxes />创建条目</h2><p className="panel-intro">创建后进入编辑页绑定版本、资源与下载位置，再发布。</p></div>
      <form className="inline-form" onSubmit={submit}>
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="条目标题，如 Ubuntu 22.04 LTS" required />
        <select value={contentType} onChange={(event) => setContentType(event.target.value)} aria-label="内容类型">
          {CONTENT_TYPES.map((type) => <option key={type} value={type}>{contentTypeLabel(type)}</option>)}
        </select>
        <input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="一句话简介（可选）" />
        <button className="primary" disabled={create.isPending}><Plus />创建草稿</button>
      </form>
      {create.error && <p className="form-error">{create.error.message}</p>}
    </section>

    <div className="small-search"><Search /><input maxLength={SEARCH_QUERY_MAX_LENGTH} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="按标题或 slug 过滤" /></div>

    {entries.isLoading ? <div className="loading">正在加载条目…</div>
      : entries.error ? <div className="empty error-state">加载失败：{entries.error.message}</div>
      : visible.length ? <section className="collection-admin-grid">{visible.map((entry) => <article className="panel collection-admin-card" key={entry.entry_id}>
        <div className="collection-admin-head"><span className="stat-icon purple"><Boxes /></span><div><h2>{entry.title}</h2><p>{entry.summary || "暂无简介"}</p></div></div>
        <dl>
          <div><dt>类型</dt><dd>{contentTypeLabel(entry.content_type)}</dd></div>
          <div><dt>状态</dt><dd>{statusLabel(entry.status as CatalogStatus)}</dd></div>
          <div><dt>可用性</dt><dd>{entry.availability === "available" ? "可用" : "不可用"}</dd></div>
          <div><dt>版本</dt><dd>{entry.releases.length}</dd></div>
        </dl>
        <div className="card-actions"><Link className="button primary" href={`/admin/catalog/entries/${entry.entry_id}`}>编辑</Link></div>
      </article>)}</section>
      : <div className="panel empty">还没有目录条目。</div>}
  </div></AdminShell>;
}
