"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, File, FileText, Image as ImageIcon, Package2, RefreshCw, Video } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PublicShell } from "@/components/PublicShell";
import { ResourceCard } from "@/components/ResourceCard";
import OfficePreview from "@/components/OfficePreview";
import PdfPreview from "@/components/PdfPreview";
import { api, formatBytes, PreviewCapability, Resource } from "@/lib/api";

type ResourceDetail = Resource & { breadcrumbs: Array<{ id: string; name: string }>; related: Resource[]; capabilities: PreviewCapability; previous: Resource | null; next: Resource | null };
type TextPreview = { content: string; truncated: boolean; size: number; encoding: string; preview_type: string };
const detailIcons = { software: Package2, image: ImageIcon, video: Video, document: FileText };

export default function ResourceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const query = useQuery({ queryKey: ["resource", id], queryFn: () => api<ResourceDetail>(`/api/resources/${id}`) });
  const item = query.data;
  if (query.isLoading) return <PublicShell><div className="page loading">正在加载资源…</div></PublicShell>;
  if (query.error) return <PublicShell><div className="page state-page"><strong>404</strong><h1>资源不可用</h1><p>{query.error.message}</p><Link href="/">返回首页</Link></div></PublicShell>;
  if (!item) return null;
  const Icon = detailIcons[item.content_type as keyof typeof detailIcons] || File;
  return <PublicShell><div className="page detail-page"><nav className="breadcrumb"><Link href="/">资源库</Link>{item.breadcrumbs.map((crumb) => <span key={crumb.id}>› <Link href={`/folder/${crumb.id}`}>{crumb.name}</Link></span>)}<span>› {item.name}</span></nav>{params.get("preview_error") && <div className="preview-notice">当前资源暂时无法预览（{params.get("preview_error")}），你仍可直接下载文件。</div>}<section className="detail-grid"><PreviewRenderer item={item} /><aside className="detail-meta"><span className={`detail-icon type-${item.content_type}`}><Icon /></span><h1>{item.name}</h1><p>{item.parent ? `所在目录：${item.parent.name}` : "CloudSite 已索引资源"}</p><dl><div><dt>类型</dt><dd>{item.extension?.toUpperCase() || item.content_type}</dd></div><div><dt>大小</dt><dd>{formatBytes(item.size)}</dd></div><div><dt>更新时间</dt><dd>{item.modified_at ? new Date(item.modified_at).toLocaleString("zh-CN") : "未知"}</dd></div></dl>{item.capabilities.can_download && <a className="button primary download-main" href={`/d/${item.id}`}><Download />立即下载</a>}</aside></section>{item.capabilities.preview_type === "image" && (item.previous || item.next) && <nav className="preview-neighbors">{item.previous ? <Link href={`/resource/${item.previous.id}`}><ChevronLeft />上一张</Link> : <span />}{item.next ? <Link href={`/resource/${item.next.id}`}>下一张<ChevronRight /></Link> : <span />}</nav>}{item.related.length > 0 && <><h2 className="subheading">同目录资源</h2><section className="resource-grid">{item.related.map((related) => <ResourceCard key={related.id} item={related} />)}</section></>}</div></PublicShell>;
}

function PreviewRenderer({ item }: { item: ResourceDetail }) {
  const [retry, setRetry] = useState(false);
  const [failed, setFailed] = useState(false);
  const text = useQuery({ queryKey: ["text-preview", item.id, retry], queryFn: () => api<TextPreview>(`/api/resources/${item.id}/text-preview${retry ? "?refresh=1" : ""}`), enabled: item.capabilities.preview_type === "text" || item.capabilities.preview_type === "markdown", retry: false });
  const previewUrl = `/p/${item.id}${retry ? "?refresh=1" : ""}`;
  const retryPreview = () => { setFailed(false); setRetry(true); text.refetch(); };
  if (!item.capabilities.can_preview || item.capabilities.preview_type === "none") return <article className="preview-panel"><Fallback item={item} message={item.capabilities.reason || "此文件适合下载后打开"} /></article>;
  if (item.capabilities.preview_type === "text" || item.capabilities.preview_type === "markdown") {
    const isMarkdown = item.capabilities.preview_type === "markdown";
    return <article className="preview-panel text-preview-panel">{text.isLoading ? <div className="loading">正在读取文本预览…</div> : text.error ? <Fallback item={item} message={text.error.message} retry={retryPreview} /> : <><header><strong>{isMarkdown ? "Markdown 预览" : "文本预览"}</strong>{text.data?.truncated && <span>内容已截断</span>}</header>{isMarkdown ? <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text.data?.content ?? ""}</ReactMarkdown></div> : <pre>{text.data?.content}</pre>}</>}</article>;
  }
  if (failed) return <article className="preview-panel"><Fallback item={item} message="当前文件暂时无法在线预览，可重新尝试或直接下载。" retry={retryPreview} /></article>;
  if (item.capabilities.preview_type === "image") return <article className="preview-panel"><img src={previewUrl} alt={item.name} onError={() => setFailed(true)} /></article>;
  if (item.capabilities.preview_type === "video") return <article className="preview-panel"><video controls preload="metadata" src={previewUrl} onError={() => setFailed(true)} /></article>;
  if (item.capabilities.preview_type === "pdf") return <article className="preview-panel pdf-preview-panel"><PdfPreview key={retry ? "r" : "i"} id={item.id} /><div className="pdf-hint">PDF 已缓存到服务器（约 1 小时自动清理），由浏览器原生阅读器显示。</div></article>;
  if (item.capabilities.preview_type === "office") return <article className="preview-panel office-preview-panel"><OfficePreview key={retry ? "r" : "i"} id={item.id} extension={item.extension} /><div className="pdf-hint">文档已缓存到服务器（约 1 小时自动清理），在浏览器端直接渲染。</div></article>;
  return <article className="preview-panel"><Fallback item={item} message="当前格式不支持在线预览" /></article>;
}

function Fallback({ item, message, retry }: { item: ResourceDetail; message: string; retry?: () => void }) {
  const Icon = detailIcons[item.content_type as keyof typeof detailIcons] || File;
  return <div className={`preview-fallback type-${item.content_type}`}><Icon /><strong>{item.extension?.toUpperCase() || "文件"}</strong><span>{message}</span>{retry && <button onClick={retry}><RefreshCw />重新尝试</button>}</div>;
}
