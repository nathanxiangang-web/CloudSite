"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function PdfPreview({ id }: { id: string }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await api<{ url: string }>(`/api/resources/${id}/pdf-preview`);
        if (!cancelled) { setUrl(result.url); setLoading(false); }
      } catch (err) {
        if (!cancelled) { setError(err instanceof Error ? err.message : "PDF 加载失败"); setLoading(false); }
      }
    })();
    return () => { cancelled = true; };
  }, [id]);

  if (loading) return <div className="loading">正在加载 PDF…</div>;
  if (error) return <div className="preview-fallback"><strong>PDF 预览失败</strong><span>{error}</span></div>;
  return <iframe title="PDF 预览" src={url} />;
}
