"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { PublicShell } from "@/components/PublicShell";
import { DownloadButton } from "@/components/DownloadButton";
import { api, Resource } from "@/lib/api";

const messages: Record<string, string> = {
  "DL-001": "资源不存在或已失效",
  "DL-002": "AList 暂时无法访问",
  "DL-003": "暂时无法获取上游下载地址",
  "DL-004": "上游下载地址已经失效",
  "DL-005": "上游服务请求过于频繁",
  "DL-006": "上游存储暂时不可用",
  "DL-007": "资源当前禁止下载",
  "DL-008": "下载地址未通过安全校验",
  "DL-999": "下载服务暂时不可用",
};

function DownloadErrorContent() {
  const params = useSearchParams();
  const code = messages[params.get("code") || ""] ? params.get("code")! : "DL-999";
  const resourceId = params.get("resource") || "";
  const resource = useQuery({ queryKey: ["download-error-resource", resourceId], queryFn: () => api<Resource & { breadcrumbs: unknown[]; related: Resource[] }>(`/api/resources/${encodeURIComponent(resourceId)}`), enabled: Boolean(resourceId) && code !== "DL-001", retry: false });
  return <PublicShell><div className="page download-error-page">
    <section className="download-error-card"><span className="download-error-icon"><AlertTriangle /></span><h1>下载暂时不可用</h1><p>{resource.data?.name || "当前资源"}</p><strong>{messages[code]}</strong><small>错误码：{code}</small><div>{resourceId && <DownloadButton resourceId={resourceId} className="button primary"><><RefreshCw />重新获取下载入口</></DownloadButton>}{resourceId && code !== "DL-001" && <Link className="button" href={`/resource/${encodeURIComponent(resourceId)}`}>返回文件详情</Link>}<Link className="button" href="/">返回首页</Link></div></section>
  </div></PublicShell>;
}

export default function DownloadErrorPage() { return <Suspense><DownloadErrorContent /></Suspense>; }
