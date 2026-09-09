"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes, ChevronLeft, Download, File, Link2, AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DownloadButton } from "@/components/DownloadButton";
import { PublicShell } from "@/components/PublicShell";
import {
  assetKindLabel,
  contentTypeLabel,
  formatCatalogTimestamp,
  pickDownloadLocation,
  releaseIsPublished,
  type CatalogAssetSummary,
} from "@/lib/catalog";
import { fetchCatalogAsset, fetchCatalogEntry, fetchCatalogRelease } from "@/lib/catalog-client";
import { formatBytes } from "@/lib/api";

export default function CatalogEntryPage() {
  const { entryId } = useParams<{ entryId: string }>();
  const entry = useQuery({ queryKey: ["catalog-entry", entryId], queryFn: () => fetchCatalogEntry(entryId) });

  if (entry.isLoading) return <PublicShell><div className="page loading">正在加载目录条目…</div></PublicShell>;
  if (entry.error) return <PublicShell><div className="page state-page"><strong>404</strong><h1>条目不可见</h1><p>{entry.error.message}</p><Link href="/catalog">返回目录</Link></div></PublicShell>;
  if (!entry.data) return null;

  const data = entry.data;
  const publishedReleases = data.releases.filter(releaseIsPublished);

  return <PublicShell><div className="page catalog-detail-page">
    <nav className="breadcrumb"><Link href="/">资源库</Link><span>›</span><Link href="/catalog">资源目录</Link><span>›</span>{data.title}</nav>
    <header className="catalog-detail-heading">
      <Link className="resource-back" href="/catalog"><ChevronLeft />资源目录</Link>
      <span className={`detail-icon type-${data.content_type}`}><Boxes /></span>
      <h1>{data.title}</h1>
      <div className="catalog-detail-meta">
        <span className="catalog-detail-kind">{contentTypeLabel(data.content_type)}</span>
        {data.availability === "unavailable" && <span className="catalog-card-unavailable"><AlertTriangle size={13} />暂不可用</span>}
        <span className="catalog-detail-updated">更新于 {formatCatalogTimestamp(data.updated_at)}</span>
      </div>
    </header>

    {data.summary && <p className="catalog-detail-summary">{data.summary}</p>}
    {data.description && <section className="markdown-body catalog-detail-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{data.description}</ReactMarkdown></section>}

    {publishedReleases.length === 0 ? <div className="empty">该条目暂无可见的已发布版本。</div>
      : <ReleasePicker releases={publishedReleases} />}

    {data.relations.length > 0 && <section className="panel catalog-relations">
      <h2>相关条目</h2>
      <ul>{data.relations.map((relation) => <li key={relation.relation_id}><Link2 size={14} /><Link href={`/catalog/${relation.to_entry_id}`}>{relation.to_title}</Link><span>{relation.relation_type}</span></li>)}</ul>
    </section>}
  </div></PublicShell>;
}

function ReleasePicker({ releases }: { releases: Array<{ release_id: string; slug: string; title: string; published_at: string | null }> }) {
  const [releaseId, setReleaseId] = useState(releases[0].release_id);
  const activeReleaseId = releases.some((release) => release.release_id === releaseId) ? releaseId : releases[0].release_id;
  const release = useQuery({ queryKey: ["catalog-release", activeReleaseId], queryFn: () => fetchCatalogRelease(activeReleaseId), enabled: Boolean(activeReleaseId) });
  const current = releases.find((item) => item.release_id === activeReleaseId);

  return <section className="catalog-release-picker">
    <div className="catalog-release-tabs">
      {releases.map((item) => <button key={item.release_id} type="button" className={item.release_id === activeReleaseId ? "selected" : ""} onClick={() => setReleaseId(item.release_id)}>{item.title}</button>)}
    </div>
    {current?.published_at && <p className="catalog-release-published">发布于 {formatCatalogTimestamp(current.published_at)}</p>}
    {release.isLoading ? <div className="loading">正在加载版本资源…</div>
      : release.error ? <div className="empty error-state">版本暂时不可用：{release.error.message}</div>
      : release.data?.assets.length ? <AssetList assets={release.data.assets} />
      : <div className="empty">该版本暂无可用资源。</div>}
  </section>;
}

function AssetList({ assets }: { assets: CatalogAssetSummary[] }) {
  const [assetId, setAssetId] = useState(assets[0].asset_id);
  const activeAssetId = assets.some((asset) => asset.asset_id === assetId) ? assetId : assets[0].asset_id;
  const asset = useQuery({ queryKey: ["catalog-asset", activeAssetId], queryFn: () => fetchCatalogAsset(activeAssetId), enabled: Boolean(activeAssetId) });
  const selected = useMemo(() => assets.find((item) => item.asset_id === activeAssetId), [assets, activeAssetId]);

  return <div className="catalog-asset-section">
    <div className="catalog-asset-tabs">
      {assets.map((item) => <button key={item.asset_id} type="button" className={item.asset_id === activeAssetId ? "selected" : ""} onClick={() => setAssetId(item.asset_id)}>
        <span className="catalog-asset-name">{item.display_name}</span>
        {item.platform && <span className="catalog-asset-platform">{item.platform}</span>}
      </button>)}
    </div>
    {selected && <article className="panel catalog-asset-detail">
      <header><span className="catalog-asset-kind">{assetKindLabel(selected.kind)}</span><h2>{selected.display_name}</h2></header>
      <dl>
        <div><dt>平台</dt><dd>{selected.platform || "通用"}</dd></div>
        <div><dt>类型</dt><dd>{assetKindLabel(selected.kind)}</dd></div>
        <div><dt>大小</dt><dd>{selected.size != null ? formatBytes(selected.size) : "以实际下载为准"}</dd></div>
        <div><dt>状态</dt><dd>{selected.availability === "available" ? "可下载" : "暂不可用"}</dd></div>
      </dl>
      {asset.isLoading ? <div className="loading">正在加载下载位置…</div>
        : asset.error ? <div className="empty error-state">下载位置暂时不可用：{asset.error.message}</div>
        : <LocationActions locations={asset.data?.locations ?? []} />}
    </article>}
  </div>;
}

function LocationActions({ locations }: { locations: Array<{ location_id: string; resource_id: string; root_mapping_id: number | null; label: string; is_primary: boolean; availability: "available" | "unavailable"; status: "active" | "disabled"; download_url: string; resource: { id: string; name: string; extension: string; size: number; content_type: string } | null }> }) {
  if (locations.length === 0) return <div className="empty compact">该资源暂无下载位置。</div>;
  const primary = pickDownloadLocation(locations);
  return <div className="catalog-locations">
    {primary && <div className="catalog-location-primary">
      <DownloadButton resourceId={primary.resource_id} className="button primary download-main"><><Download />立即下载{primary.resource?.extension ? `（${primary.resource.extension.toUpperCase()}）` : ""}</></DownloadButton>
      {primary.label && <span className="catalog-location-label">推荐位置：{primary.label}</span>}
    </div>}
    <ul className="catalog-location-list">
      {locations.map((location) => <li key={location.location_id} className={location.availability === "available" ? "" : "unavailable"}>
        <span className="catalog-location-name">{location.label || location.resource?.name || location.resource_id}</span>
        {location.is_primary && <span className="catalog-location-primary-tag">主</span>}
        {location.availability === "available" ? <DownloadButton resourceId={location.resource_id} className="button" compact ariaLabel="下载该位置"><><Download size={15} /></></DownloadButton> : <span className="catalog-location-unavailable">不可用</span>}
      </li>)}
    </ul>
  </div>;
}
