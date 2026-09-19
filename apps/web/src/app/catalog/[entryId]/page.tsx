"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes, ChevronLeft, Download, Link2, AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PublicShell } from "@/components/PublicShell";
import { CatalogFollowButton } from "@/components/catalog/CatalogFollowButton";
import {
  assetDimensionLabel,
  assetKindLabel,
  channelLabel,
  contentTypeLabel,
  formatCatalogTimestamp,
  releaseIsHistorical,
  releaseIsPublished,
  releaseIsRecommended,
  type CatalogAssetSummary,
} from "@/lib/catalog";
import { catalogAssetDownloadPath, fetchCatalogEntry, fetchCatalogRelease } from "@/lib/catalog-client";
import { ApiError, formatBytes } from "@/lib/api";

export default function CatalogEntryPage() {
  const { entryId } = useParams<{ entryId: string }>();
  const entry = useQuery({ queryKey: ["catalog-entry", entryId], queryFn: () => fetchCatalogEntry(entryId) });

  if (entry.isLoading) return <PublicShell><div className="page loading">正在加载目录条目…</div></PublicShell>;
  if (entry.error) {
    const notFound = entry.error instanceof ApiError && entry.error.status === 404;
    return <PublicShell><div className={`page state-page${notFound ? "" : " error-state"}`}><strong>{notFound ? "404" : "加载失败"}</strong><h1>{notFound ? "条目不可见" : "目录条目暂时不可用"}</h1><p>{entry.error.message}</p>{notFound ? <Link href="/catalog">返回目录</Link> : <button type="button" onClick={() => entry.refetch()}>重试</button>}</div></PublicShell>;
  }
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
      <div className="catalog-detail-follow"><CatalogFollowButton entryId={data.entry_id} /></div>
    </header>

    {data.summary && <p className="catalog-detail-summary">{data.summary}</p>}
    {data.description && <section className="markdown-body catalog-detail-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{data.description}</ReactMarkdown></section>}

    {publishedReleases.length === 0 ? <div className="empty">该条目暂无可见的已发布版本。</div>
      : <ReleasePicker entryId={data.entry_id} releases={publishedReleases} />}

    {data.relations.length > 0 && <section className="panel catalog-relations">
      <h2>相关条目</h2>
      <ul>{data.relations.map((relation) => <li key={relation.relation_id}><Link2 size={14} /><Link href={`/catalog/${relation.to_entry_id}`}>{relation.to_title}</Link><span>{relation.relation_type}</span></li>)}</ul>
    </section>}
  </div></PublicShell>;
}

function ReleasePicker({ entryId, releases }: { entryId: string; releases: Array<{ release_id: string; slug: string; title: string; channel: string; is_recommended: boolean; release_date: string | null; published_at: string | null }> }) {
  const sorted = useMemo(() => {
    const recommended = releases.find(releaseIsRecommended);
    const rest = releases.filter((release) => !releaseIsRecommended(release));
    rest.sort((a, b) => (releaseIsHistorical(b) ? -1 : 0) - (releaseIsHistorical(a) ? -1 : 0));
    return recommended ? [recommended, ...rest] : rest;
  }, [releases]);
  const [releaseId, setReleaseId] = useState(sorted[0]?.release_id ?? "");
  const activeReleaseId = sorted.some((release) => release.release_id === releaseId) ? releaseId : (sorted[0]?.release_id ?? "");
  const release = useQuery({ queryKey: ["catalog-release", activeReleaseId], queryFn: () => fetchCatalogRelease(activeReleaseId), enabled: Boolean(activeReleaseId) });
  const current = sorted.find((item) => item.release_id === activeReleaseId);

  return <section className="catalog-release-picker">
    <div className="catalog-release-tabs">
      {sorted.map((item) => <button key={item.release_id} type="button" className={item.release_id === activeReleaseId ? "selected" : ""} onClick={() => setReleaseId(item.release_id)}>
        <span className="catalog-release-title">{item.title}</span>
        <span className="catalog-release-channel">{channelLabel(item.channel)}</span>
        {releaseIsRecommended(item) && <span className="catalog-release-recommend">推荐</span>}
      </button>)}
    </div>
    {current?.published_at && <p className="catalog-release-published">发布于 {formatCatalogTimestamp(current.published_at)}{current.release_date ? `（版本日期 ${formatCatalogTimestamp(current.release_date)}）` : ""}</p>}
    {release.isLoading ? <div className="loading">正在加载版本资源…</div>
      : release.error ? <div className="empty error-state">版本暂时不可用：{release.error.message}<button type="button" onClick={() => release.refetch()}>重试</button></div>
      : release.data?.assets.length ? <AssetList entryId={entryId} assets={release.data.assets} />
      : <div className="empty">该版本暂无可用资源。</div>}
  </section>;
}

function AssetList({ entryId, assets }: { entryId: string; assets: CatalogAssetSummary[] }) {
  const platforms = useMemo(() => Array.from(new Set(assets.map((asset) => asset.platform || "通用"))), [assets]);
  const archs = useMemo(() => Array.from(new Set(assets.map((asset) => asset.architecture || "unknown"))), [assets]);
  const packageTypes = useMemo(() => Array.from(new Set(assets.map((asset) => asset.package_type || "unknown"))), [assets]);
  const [platform, setPlatform] = useState("");
  const [arch, setArch] = useState("");
  const [packageType, setPackageType] = useState("");
  const filtered = useMemo(() => assets.filter((asset) => (!platform || (asset.platform || "通用") === platform) && (!arch || (asset.architecture || "unknown") === arch) && (!packageType || (asset.package_type || "unknown") === packageType)), [assets, platform, arch, packageType]);

  return <div className="catalog-asset-section">
    {(platforms.length > 1 || archs.length > 1 || packageTypes.length > 1) && <div className="catalog-asset-filters">
      {platforms.length > 1 && <select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="">全部平台</option>{platforms.map((value) => <option key={value} value={value}>{value}</option>)}</select>}
      {archs.length > 1 && <select value={arch} onChange={(event) => setArch(event.target.value)}><option value="">全部架构</option>{archs.map((value) => <option key={value} value={value}>{assetDimensionLabel(value, "未知")}</option>)}</select>}
      {packageTypes.length > 1 && <select value={packageType} onChange={(event) => setPackageType(event.target.value)}><option value="">全部包型</option>{packageTypes.map((value) => <option key={value} value={value}>{assetDimensionLabel(value, "未知")}</option>)}</select>}
    </div>}
    {filtered.length === 0 ? <div className="empty compact">没有符合筛选条件的交付物。</div>
      : <div className="catalog-asset-grid">{filtered.map((asset) => <article key={asset.asset_id} className="panel catalog-asset-card">
        <header><span className="catalog-asset-kind">{assetKindLabel(asset.kind)}</span><h3>{asset.display_name}</h3></header>
        <dl>
          <div><dt>平台</dt><dd>{assetDimensionLabel(asset.platform, "通用")}</dd></div>
          <div><dt>架构</dt><dd>{assetDimensionLabel(asset.architecture, "未知")}</dd></div>
          <div><dt>包型</dt><dd>{assetDimensionLabel(asset.package_type, "未知")}</dd></div>
          <div><dt>语言</dt><dd>{assetDimensionLabel(asset.language, "未知")}</dd></div>
          <div><dt>大小</dt><dd>{asset.size != null ? formatBytes(asset.size) : "以实际下载为准"}</dd></div>
          <div><dt>状态</dt><dd className={asset.availability === "available" ? "available" : "unavailable"}>{asset.availability === "available" ? "可下载" : "暂不可用"}</dd></div>
        </dl>
        <AssetDownloadButton entryId={entryId} assetId={asset.asset_id} available={asset.availability === "available"} />
      </article>)}</div>}
  </div>;
}

function AssetDownloadButton({ entryId, assetId, available }: { entryId: string; assetId: string; available: boolean }) {
  const formRef = useRef<HTMLFormElement>(null);
  return (
    <form ref={formRef} action={catalogAssetDownloadPath(entryId, assetId)} method="POST" className="catalog-asset-download-form">
      <button type="submit" className="button primary download-main" disabled={!available} aria-disabled={!available}>
        <Download size={16} />{available ? "立即下载" : "暂不可用"}
      </button>
    </form>
  );
}
