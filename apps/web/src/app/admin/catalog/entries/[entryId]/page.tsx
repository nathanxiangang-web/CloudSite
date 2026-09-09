"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Boxes, Check, ChevronLeft, Eye, File, Plus, Search, Star, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { api, formatBytes, SearchResponse } from "@/lib/api";
import { SEARCH_QUERY_MAX_LENGTH } from "@/lib/search-query";
import {
  contentTypeLabel,
  statusLabel,
  type CatalogAssetKind,
  type CatalogStatus,
} from "@/lib/catalog";
import {
  attachAdminCatalogLocation,
  createAdminCatalogAsset,
  createAdminCatalogRelease,
  deleteAdminCatalogAsset,
  deleteAdminCatalogRelease,
  detachAdminCatalogLocation,
  fetchAdminCatalogEntry,
  fetchAdminCatalogReleases,
  fetchAdminCatalogAssets,
  fetchAdminCatalogLocations,
  publishAdminCatalogEntry,
  updateAdminCatalogAsset,
  updateAdminCatalogEntry,
  updateAdminCatalogLocation,
  updateAdminCatalogRelease,
} from "@/lib/catalog-client";

const CONTENT_TYPES = ["software", "image", "video", "document", "file"];
const ASSET_KINDS: CatalogAssetKind[] = ["file", "document", "image", "video", "archive", "other"];
const ENTRY_STATUSES: CatalogStatus[] = ["draft", "published", "archived", "disabled"];
const RELEASE_STATUSES: CatalogStatus[] = ["draft", "published", "archived", "disabled"];

export default function AdminCatalogEntryEditor() {
  const { entryId } = useParams<{ entryId: string }>();
  const client = useQueryClient();
  const entry = useQuery({ queryKey: ["admin-catalog-entry", entryId], queryFn: () => fetchAdminCatalogEntry(entryId) });

  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [contentType, setContentType] = useState("software");
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<CatalogStatus>("draft");
  const [coverResourceId, setCoverResourceId] = useState("");
  const [synced, setSynced] = useState(entry.data);

  if (entry.data !== synced) {
    setSynced(entry.data);
    if (entry.data) {
      setTitle(entry.data.title);
      setSlug(entry.data.slug);
      setContentType(entry.data.content_type);
      setSummary(entry.data.summary);
      setDescription(entry.data.description);
      setStatus(entry.data.status);
      setCoverResourceId(entry.data.cover_resource_id ?? "");
    }
  }

  const save = useMutation({
    mutationFn: () => {
      if (!entry.data) throw new Error("条目尚未加载");
      return updateAdminCatalogEntry(entryId, { expected_revision: entry.data.revision, title: title.trim(), slug: slug.trim() || undefined, content_type: contentType, summary, description, cover_resource_id: coverResourceId || null, status });
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-catalog-entry", entryId] }); client.invalidateQueries({ queryKey: ["admin-catalog-entries"] }); },
  });
  const publish = useMutation({
    mutationFn: () => {
      if (!entry.data) throw new Error("条目尚未加载");
      return publishAdminCatalogEntry(entryId, entry.data.revision);
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-catalog-entry", entryId] }); client.invalidateQueries({ queryKey: ["admin-catalog-entries"] }); },
  });
  const unpublish = useMutation({
    mutationFn: () => {
      if (!entry.data) throw new Error("条目尚未加载");
      return updateAdminCatalogEntry(entryId, { expected_revision: entry.data.revision, status: "draft" });
    },
    onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-catalog-entry", entryId] }); client.invalidateQueries({ queryKey: ["admin-catalog-entries"] }); },
  });

  if (entry.isLoading) return <AdminShell title="编辑目录条目"><div className="panel loading">正在加载条目…</div></AdminShell>;
  if (entry.error) return <AdminShell title="编辑目录条目"><div className="panel empty error-state">加载失败：{entry.error.message}<div className="card-actions"><Link className="button" href="/admin/catalog/entries">返回列表</Link></div></div></AdminShell>;
  if (!entry.data) return null;

  return <AdminShell title={`编辑条目：${entry.data.title}`}><div className="admin-page">
    <div className="catalog-editor-toolbar">
      <Link className="back-link" href="/admin/catalog/entries"><ArrowLeft />返回列表</Link>
      <div className="card-actions">
        <Link className="button" href={`/catalog/${entryId}`} target="_blank"><Eye />预览</Link>
        {status === "published" ? <button className="button" disabled={unpublish.isPending} onClick={() => unpublish.mutate()}>取消发布</button> : <button className="primary" disabled={publish.isPending} onClick={() => publish.mutate()}>发布</button>}
      </div>
    </div>

    <section className="panel catalog-editor-section">
      <h2>条目信息</h2>
      <div className="form-stack">
        <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
        <div className="collection-editor-row">
          <label>内容类型<select value={contentType} onChange={(event) => setContentType(event.target.value)}>{CONTENT_TYPES.map((type) => <option key={type} value={type}>{contentTypeLabel(type)}</option>)}</select></label>
          <label>状态<select value={status} onChange={(event) => setStatus(event.target.value as CatalogStatus)}>{ENTRY_STATUSES.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
          <label>封面资源 ID<input value={coverResourceId} onChange={(event) => setCoverResourceId(event.target.value)} placeholder="可选图片资源 ID" /></label>
        </div>
        <label>Slug（留空由后端生成）<input value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="url-safe-slug" /></label>
        <label>简介<textarea value={summary} onChange={(event) => setSummary(event.target.value)} rows={2} /></label>
        <label>正文（Markdown）<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={6} /></label>
      </div>
      <div className="form-actions"><button className="primary" disabled={save.isPending} onClick={() => save.mutate()}>保存条目</button></div>
      {save.error && <p className="form-error">{save.error.message}</p>}
      {publish.error && <p className="form-error">{publish.error.message}</p>}
      {unpublish.error && <p className="form-error">{unpublish.error.message}</p>}
    </section>

    <ReleaseManager entryId={entryId} />
  </div></AdminShell>;
}

function ReleaseManager({ entryId }: { entryId: string }) {
  const client = useQueryClient();
  const releases = useQuery({ queryKey: ["admin-catalog-releases", entryId], queryFn: () => fetchAdminCatalogReleases(entryId) });
  const [newTitle, setNewTitle] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [selectedRelease, setSelectedRelease] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => createAdminCatalogRelease(entryId, { slug: newSlug.trim() || "v1", title: newTitle.trim() || "默认版本", status: "draft" }),
    onSuccess: (data) => { setNewTitle(""); setNewSlug(""); client.invalidateQueries({ queryKey: ["admin-catalog-releases", entryId] }); setSelectedRelease(data.release_id); },
  });
  const remove = useMutation({ mutationFn: (releaseId: string) => deleteAdminCatalogRelease(releaseId), onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-catalog-releases", entryId] }); setSelectedRelease(null); } });

  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate(); };
  const items = releases.data?.items ?? [];

  return <section className="panel catalog-editor-section">
    <h2>版本（{items.length}）</h2>
    <form className="inline-form" onSubmit={submit}>
      <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="版本标题，如 22.04.3" />
      <input value={newSlug} onChange={(event) => setNewSlug(event.target.value)} placeholder="slug，如 22.04.3" />
      <button className="primary" disabled={create.isPending}><Plus />新增版本</button>
    </form>
    {create.error && <p className="form-error">{create.error.message}</p>}

    {releases.isLoading ? <div className="loading">正在加载版本…</div>
      : items.length ? <div className="catalog-release-list">{items.map((release) => <div className="catalog-release-row" key={release.release_id}>
        <button type="button" className={selectedRelease === release.release_id ? "selected" : ""} onClick={() => setSelectedRelease(release.release_id)}>
          <strong>{release.title}</strong>
          <span>{statusLabel(release.status)} · {release.assets.length} 个资源</span>
        </button>
        <ReleaseStatusSelect entryId={entryId} releaseId={release.release_id} current={release.status} />
        <button className="danger" onClick={() => window.confirm(`删除版本“${release.title}”？`) && remove.mutate(release.release_id)}><Trash2 /></button>
      </div>)}</div>
      : <div className="empty compact">还没有版本，先新增一个。</div>}

    {selectedRelease && <AssetManager entryId={entryId} releaseId={selectedRelease} />}
  </section>;
}

function ReleaseStatusSelect({ entryId, releaseId, current }: { entryId: string; releaseId: string; current: CatalogStatus }) {
  const client = useQueryClient();
  const update = useMutation({
    mutationFn: (next: CatalogStatus) => updateAdminCatalogRelease(releaseId, { status: next }),
    onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-catalog-releases", entryId] }); },
  });
  return <select value={current} onChange={(event) => { const next = event.target.value as CatalogStatus; update.mutate(next); }}>{RELEASE_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</select>;
}

function AssetManager({ entryId, releaseId }: { entryId: string; releaseId: string }) {
  const client = useQueryClient();
  const assets = useQuery({ queryKey: ["admin-catalog-assets", releaseId], queryFn: () => fetchAdminCatalogAssets(releaseId) });
  const [displayName, setDisplayName] = useState("");
  const [platform, setPlatform] = useState("");
  const [kind, setKind] = useState<CatalogAssetKind>("file");
  const [selectedAsset, setSelectedAsset] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => createAdminCatalogAsset(releaseId, { slug: displayName.trim().toLowerCase().replace(/\s+/g, "-") || `asset-${Date.now()}`, display_name: displayName.trim(), platform: platform.trim(), kind }),
    onSuccess: (data) => { setDisplayName(""); setPlatform(""); client.invalidateQueries({ queryKey: ["admin-catalog-assets", releaseId] }); setSelectedAsset(data.asset_id); },
  });
  const remove = useMutation({ mutationFn: (assetId: string) => deleteAdminCatalogAsset(assetId), onSuccess: () => { client.invalidateQueries({ queryKey: ["admin-catalog-assets", releaseId] }); setSelectedAsset(null); } });

  const items = assets.data?.items ?? [];

  return <div className="catalog-asset-manager">
    <h3>版本资源（{items.length}）</h3>
    <form className="inline-form" onSubmit={(event) => { event.preventDefault(); if (displayName.trim()) create.mutate(); }}>
      <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="资源显示名，如 ubuntu-22.04.3-desktop-amd64.iso" required />
      <input value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="平台，如 amd64（可选）" />
      <select value={kind} onChange={(event) => setKind(event.target.value as CatalogAssetKind)}>{ASSET_KINDS.map((value) => <option key={value} value={value}>{value}</option>)}</select>
      <button className="primary" disabled={create.isPending}><Plus />新增资源</button>
    </form>
    {create.error && <p className="form-error">{create.error.message}</p>}

    {assets.isLoading ? <div className="loading">正在加载资源…</div>
      : items.length ? <div className="catalog-asset-list">{items.map((asset) => <div className="catalog-asset-row" key={asset.asset_id}>
        <button type="button" className={selectedAsset === asset.asset_id ? "selected" : ""} onClick={() => setSelectedAsset(asset.asset_id)}>
          <strong>{asset.display_name}</strong>
          <span>{asset.platform || "通用"} · {asset.location_count} 个位置 · {asset.availability === "available" ? "可用" : "不可用"}</span>
        </button>
        <button className="danger" onClick={() => window.confirm(`删除资源“${asset.display_name}”？`) && remove.mutate(asset.asset_id)}><Trash2 /></button>
      </div>)}</div>
      : <div className="empty compact">还没有资源，先新增一个。</div>}

    {selectedAsset && <LocationManager entryId={entryId} releaseId={releaseId} assetId={selectedAsset} />}
  </div>;
}

function LocationManager({ entryId, releaseId, assetId }: { entryId: string; releaseId: string; assetId: string }) {
  const client = useQueryClient();
  const locations = useQuery({ queryKey: ["admin-catalog-locations", assetId], queryFn: () => fetchAdminCatalogLocations(assetId) });
  const [searchQuery, setSearchQuery] = useState("");
  const search = useQuery({ queryKey: ["catalog-file-picker", searchQuery], queryFn: () => api<SearchResponse>(`/api/search?q=${encodeURIComponent(searchQuery)}&object_type=resource&page_size=20`), enabled: searchQuery.trim().length > 0 });

  const invalidate = () => { client.invalidateQueries({ queryKey: ["admin-catalog-locations", assetId] }); client.invalidateQueries({ queryKey: ["admin-catalog-assets", releaseId] }); client.invalidateQueries({ queryKey: ["admin-catalog-releases", entryId] }); client.invalidateQueries({ queryKey: ["admin-catalog-entry", entryId] }); };
  const attach = useMutation({ mutationFn: (resourceId: string) => attachAdminCatalogLocation(assetId, { resource_id: resourceId }), onSuccess: invalidate });
  const detach = useMutation({ mutationFn: (locationId: string) => detachAdminCatalogLocation(locationId), onSuccess: invalidate });
  const setPrimary = useMutation({ mutationFn: (locationId: string) => updateAdminCatalogLocation(locationId, { is_primary: true }), onSuccess: invalidate });

  const items = locations.data?.items ?? [];
  const attachedIds = new Set(items.map((location) => location.resource_id));

  return <div className="catalog-location-manager">
    <h4>下载位置（{items.length}）</h4>
    {locations.isLoading ? <div className="loading">正在加载位置…</div>
      : items.length ? <div className="picker-items">{items.map((location) => <div className="picker-item" key={location.location_id}>
        <span className="picker-item-icon type-software"><File /></span>
        <span className="picker-item-copy"><strong>{location.label || location.resource?.name || location.resource_id}</strong><small>{location.availability === "available" ? "可用" : "不可用"}{location.resource?.size ? ` · ${formatBytes(location.resource.size)}` : ""}</small></span>
        {location.is_primary ? <button disabled><Star fill="currentColor" />主</button> : <button onClick={() => setPrimary.mutate(location.location_id)} title="设为主位置"><Star /></button>}
        <button className="danger" onClick={() => detach.mutate(location.location_id)}><Trash2 /></button>
      </div>)}</div>
      : <div className="empty compact">尚未绑定下载位置。</div>}
    {(attach.error || detach.error || setPrimary.error) && <p className="form-error">{(attach.error ?? detach.error ?? setPrimary.error)?.message}</p>}

    <h4>绑定已索引文件</h4>
    <div className="small-search"><Search /><input maxLength={SEARCH_QUERY_MAX_LENGTH} value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索资源名称，选择后绑定为下载位置" /></div>
    <div className="picker-results">{search.isLoading ? <div className="loading">搜索中…</div>
      : search.data?.items.filter((resource) => resource.object_type === "resource").map((resource) => { const attached = attachedIds.has(resource.id); return <div className="picker-item" key={resource.id}>
        <span className="picker-item-icon type-software"><File /></span>
        <span className="picker-item-copy"><strong>{resource.name}</strong><small>{resource.extension ? resource.extension.toUpperCase() : ""}{resource.size != null ? ` · ${formatBytes(resource.size)}` : ""}</small></span>
        {attached ? <button disabled><Check />已绑定</button> : <button className="primary" onClick={() => attach.mutate(resource.id)}><Plus />绑定</button>}
      </div>; })}</div>
  </div>;
}
