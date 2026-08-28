"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] as string));
}

function slideNumber(name: string): number {
  const match = /slide(\d+)\.xml$/.exec(name);
  return match ? Number(match[1]) : 0;
}

async function renderOffice(arrayBuffer: ArrayBuffer, extension: string): Promise<string> {
  const ext = extension.toLowerCase();
  if (ext === "docx" || ext === "doc") {
    const mammoth = await import("mammoth");
    const result = await mammoth.convertToHtml({ arrayBuffer });
    return result.value;
  }
  if (ext === "xlsx" || ext === "xls") {
    const XLSX = await import("xlsx");
    const workbook = XLSX.read(arrayBuffer, { type: "array" });
    return workbook.SheetNames.map((name) => `<h3 class="office-sheet-name">${escapeHtml(name)}</h3>${XLSX.utils.sheet_to_html(workbook.Sheets[name])}`).join("");
  }
  if (ext === "pptx" || ext === "ppt") {
    const JSZip = (await import("jszip")).default;
    const zip = await JSZip.loadAsync(arrayBuffer);
    const slideFiles = Object.keys(zip.files).filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name)).sort((a, b) => slideNumber(a) - slideNumber(b));
    const slides: string[] = [];
    for (const file of slideFiles) {
      const xml = await zip.files[file].async("text");
      const texts = [...xml.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map((m) => m[1]).filter((t) => t.trim()).join(" ");
      slides.push(`<div class="pptx-slide"><h4>第 ${slides.length + 1} 页</h4><p>${escapeHtml(texts || "（本页无可提取文本）")}</p></div>`);
    }
    return slides.length ? slides.join("") : "<p>未能在该演示文稿中提取到文本。</p>";
  }
  throw new Error("不支持的 Office 格式");
}

export default function OfficePreview({ id, extension }: { id: string; extension: string }) {
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { url } = await api<{ url: string }>(`/api/resources/${id}/office-preview`);
        const response = await fetch(url);
        if (!response.ok) throw new Error("预览文件加载失败");
        const rendered = await renderOffice(await response.arrayBuffer(), extension);
        if (!cancelled) { setHtml(rendered); setLoading(false); }
      } catch (err) {
        if (!cancelled) { setError(err instanceof Error ? err.message : "预览失败"); setLoading(false); }
      }
    })();
    return () => { cancelled = true; };
  }, [id, extension]);

  if (loading) return <div className="loading">正在下载并渲染文档…</div>;
  if (error) return <div className="preview-fallback"><strong>{extension.toUpperCase()} 预览失败</strong><span>{error}</span></div>;
  return <div className="office-rendered" dangerouslySetInnerHTML={{ __html: html }} />;
}
