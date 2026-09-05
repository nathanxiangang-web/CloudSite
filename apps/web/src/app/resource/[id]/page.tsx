"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ChevronLeft, ChevronRight, Download, File, FileText, Heart, Image as ImageIcon, Package2, RefreshCw, Share2, Video } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DownloadButton } from "@/components/DownloadButton";
import OfficePreview from "@/components/OfficePreview";
import PdfPreview from "@/components/PdfPreview";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import { ShareDialog } from "@/components/ShareDialog";
import { VideoPlayer } from "@/components/video/VideoPlayer";
import { api, formatBytes, PreviewCapability, Resource } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type ResourceDetail = Resource & { breadcrumbs: Array<{ id: string; name: string }>; related: Resource[]; capabilities: PreviewCapability; previous: Resource | null; next: Resource | null };
type TextPreview = { content: string; truncated: boolean; size: number; encoding: string; preview_type: string };
const detailIcons = { software: Package2, image: ImageIcon, video: Video, document: FileText };
const archiveExtensions = new Set(["7z", "bz2", "gz", "rar", "tar", "xz", "zip"]);

function formatModifiedAt(value: string | null | undefined) {
  if (!value) return "未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export default function ResourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const auth = useAuth();
  const [shareOpen, setShareOpen] = useState(false);
  const query = useQuery({ queryKey: ["resource", id], queryFn: () => api<ResourceDetail>(`/api/resources/${id}`) });
  const item = query.data;

  useEffect(() => {
    if (!item || !auth.data?.authenticated) return;
    void api(`/api/me/history/${item.id}/touch`, { method: "POST" }).catch(() => { /* 历史失败不阻塞详情页 */ });
  }, [item, auth.data?.authenticated]);

  if (query.isLoading) return <PublicShell><div className="page loading">正在加载资源…</div></PublicShell>;
  if (query.error) return <PublicShell><div className="page state-page"><strong>404</strong><h1>资源不可用</h1><p>{query.error.message}</p><Link href="/">返回首页</Link></div></PublicShell>;
  if (!item) return null;
  const Icon = detailIcons[item.content_type as keyof typeof detailIcons] || File;
  const isSoftware = item.content_type === "software";
  const extension = item.extension?.toUpperCase() || item.content_type;
  const modifiedAt = formatModifiedAt(item.modified_at);
  const parentHref = item.parent ? `/folder/${item.parent.id}` : "/";
  const parentName = item.parent?.name || "资源库";

  return <PublicShell><div className="page detail-page">
    <nav className="breadcrumb"><Link href="/">资源库</Link>{item.breadcrumbs.map((crumb) => <span key={crumb.id}>› <Link href={`/folder/${crumb.id}`}>{crumb.name}</Link></span>)}</nav>
    <header className="resource-heading">
      <Link className="resource-back" href={parentHref}><ChevronLeft />{parentName}</Link>
      <h1>{item.name}</h1>
    </header>
    {params.get("preview_error") && <div className="preview-notice">当前资源暂时无法预览（{params.get("preview_error")}），你仍可直接下载文件。</div>}
    {isSoftware ? <SoftwareOverview item={item} authenticated={Boolean(auth.data?.authenticated)} onShare={() => setShareOpen(true)} /> : <section className="detail-grid">
      <PreviewRenderer item={item} />
      <aside className="detail-meta">
        <span className={`detail-icon type-${item.content_type}`}><Icon /></span>
        <p>{item.parent ? `所在目录：${item.parent.name}` : "CloudSite 已索引资源"}</p>
        <dl><div><dt>类型</dt><dd>{extension}</dd></div><div><dt>大小</dt><dd>{formatBytes(item.size)}</dd></div><div><dt>更新时间</dt><dd>{modifiedAt}</dd></div></dl>
        <div className="detail-actions">
          {item.capabilities.can_download && <DownloadButton resourceId={item.id} className="button primary download-main"><><Download />下载</></DownloadButton>}
          <button type="button" onClick={() => setShareOpen(true)}><Share2 />分享</button>
          {auth.data?.authenticated && <FavoriteButton resourceId={item.id} />}
        </div>
      </aside>
    </section>}
    {item.capabilities.preview_type === "image" && (item.previous || item.next) && <nav className="preview-neighbors">{item.previous ? <Link href={`/resource/${item.previous.id}`}><ChevronLeft />上一张</Link> : <span />}{item.next ? <Link href={`/resource/${item.next.id}`}>下一张<ChevronRight /></Link> : <span />}</nav>}
    {item.related.length > 0 && <><h2 className="subheading">同目录资源</h2><section className="resource-grid">{item.related.map((related) => <ResourceCard key={related.id} item={related} />)}</section></>}
    {shareOpen && <ShareDialog resource={item} onClose={() => setShareOpen(false)} />}
  </div></PublicShell>;
}

function FavoriteButton({ resourceId }: { resourceId: string }) {
  const queryClient = useQueryClient();
  const key = ["favorite-status", resourceId];
  const status = useQuery({ queryKey: key, queryFn: () => api<{ favorited: boolean }>(`/api/me/favorites/${resourceId}`), retry: false });
  const mutation = useMutation({
    mutationFn: (favorited: boolean) => api(`/api/me/favorites/${resourceId}`, { method: favorited ? "DELETE" : "POST" }),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<{ favorited: boolean }>(key);
      queryClient.setQueryData(key, { favorited: !previous?.favorited });
      return previous;
    },
    onError: (_error, _value, previous) => queryClient.setQueryData(key, previous),
    onSettled: () => queryClient.invalidateQueries({ queryKey: key }),
  });
  const favorited = status.data?.favorited || false;
  return <button type="button" className={`favorite-button${favorited ? " active" : ""}`} disabled={status.isLoading || mutation.isPending} onClick={() => mutation.mutate(favorited)}><Heart fill={favorited ? "currentColor" : "none"} />{favorited ? "已收藏" : "收藏"}</button>;
}

function SoftwareOverview({ item, authenticated, onShare }: { item: ResourceDetail; authenticated: boolean; onShare: () => void }) {
  const ext = item.extension?.toUpperCase() || "文件";
  const SoftwareIcon = archiveExtensions.has(item.extension?.toLowerCase() || "") ? Archive : Package2;
  return <article className="software-info-card">
    <header className="software-info-heading">
      <span className="software-info-icon type-software"><SoftwareIcon /></span>
      <span className="software-info-kind">软件文件</span>
      <h2>{ext}</h2>
      <p>下载后可在本地打开</p>
    </header>
    <dl className="software-info-list">
      <div><dt>类型</dt><dd>{ext}</dd></div>
      <div><dt>大小</dt><dd>{formatBytes(item.size)}</dd></div>
      <div><dt>更新时间</dt><dd>{formatModifiedAt(item.modified_at)}</dd></div>
      <div><dt>所在目录</dt><dd>{item.parent?.name || "资源库"}</dd></div>
    </dl>
    <div className="software-info-actions">
      {item.capabilities.can_download && <DownloadButton resourceId={item.id} className="button primary"><><Download />下载</></DownloadButton>}
      <button type="button" onClick={onShare}><Share2 />分享</button>
      {authenticated && <FavoriteButton resourceId={item.id} />}
    </div>
  </article>;
}

function PreviewRenderer({ item }: { item: ResourceDetail }) {
  const [retry, setRetry] = useState(false);
  const [failed, setFailed] = useState(false);
  const text = useQuery({ queryKey: ["text-preview", item.id, retry], queryFn: () => api<TextPreview>(`/api/resources/${item.id}/text-preview${retry ? "?refresh=1" : ""}`), enabled: item.capabilities.preview_type === "text" || item.capabilities.preview_type === "markdown", retry: false });
  const previewGateway = item.capabilities.gateway_url || `/p/${item.id}`;
  const previewUrl = `${previewGateway}${retry ? `${previewGateway.includes("?") ? "&" : "?"}refresh=1` : ""}`;
  const retryPreview = () => { setFailed(false); setRetry(true); text.refetch(); };
  if (!item.capabilities.can_preview || item.capabilities.preview_type === "none") return <article className="preview-panel"><Fallback item={item} message={item.capabilities.reason || "此文件适合下载后打开"} /></article>;
  if (item.capabilities.preview_type === "text" || item.capabilities.preview_type === "markdown") {
    const isMarkdown = item.capabilities.preview_type === "markdown";
    return <article className="preview-panel text-preview-panel">{text.isLoading ? <div className="loading">正在读取文本预览…</div> : text.error ? <Fallback item={item} message={text.error.message} retry={retryPreview} /> : <><header><strong>{isMarkdown ? "Markdown 预览" : "文本预览"}</strong>{text.data?.truncated && <span>内容已截断</span>}</header>{isMarkdown ? <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text.data?.content ?? ""}</ReactMarkdown></div> : <pre>{text.data?.content}</pre>}</>}</article>;
  }
  if (failed) return <article className="preview-panel"><Fallback item={item} message="当前文件暂时无法在线预览，可重新尝试或直接下载。" retry={retryPreview} /></article>;
  if (item.capabilities.preview_type === "image") return <article className="preview-panel"><img src={previewUrl} alt={item.name} onError={() => setFailed(true)} /></article>;
  if (item.capabilities.preview_type === "video") return <article className="preview-panel video-preview-panel"><VideoPlayer resourceId={item.id} name={item.name} gatewayUrl={item.capabilities.gateway_url || `/p/${item.id}`} /></article>;
  if (item.capabilities.preview_type === "pdf") return <article className="preview-panel pdf-preview-panel"><PdfPreview key={retry ? "r" : "i"} id={item.id} /><div className="pdf-hint">PDF 已缓存到服务器（约 1 小时自动清理），由浏览器原生阅读器显示。</div></article>;
  if (item.capabilities.preview_type === "office") return <article className="preview-panel office-preview-panel"><OfficePreview key={retry ? "r" : "i"} id={item.id} extension={item.extension} /><div className="pdf-hint">文档已缓存到服务器（约 1 小时自动清理），在浏览器端直接渲染。</div></article>;
  return <article className="preview-panel"><Fallback item={item} message="当前格式不支持在线预览" /></article>;
}

function Fallback({ item, message, retry }: { item: ResourceDetail; message: string; retry?: () => void }) {
  const Icon = detailIcons[item.content_type as keyof typeof detailIcons] || File;
  const ext = item.extension?.toUpperCase() || "文件";
  const typeLabels: Record<string, string> = { software: "软件", image: "图库", video: "视频", document: "教程", file: "文件" };
  const typeLabel = typeLabels[item.content_type] || "文件";
  return <div className={`preview-fallback file-overview type-${item.content_type}`}>
    <div className="file-overview-icon"><Icon /><em>{ext}</em></div>
    <div className="file-overview-body">
      <strong>{item.name}</strong>
      <div className="file-overview-tags"><span>{formatBytes(item.size)}</span><span>{typeLabel}文件</span></div>
      {item.parent && <div className="file-overview-path">所在目录：{item.parent.name}</div>}
      <div className="file-overview-time">更新时间：{item.modified_at ? new Date(item.modified_at).toLocaleString("zh-CN") : "未知"}</div>
      <p>{message}</p>
      {retry && <button onClick={retry}><RefreshCw />重新尝试</button>}
    </div>
  </div>;
}
