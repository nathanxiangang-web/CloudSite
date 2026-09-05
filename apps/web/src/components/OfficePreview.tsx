"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch] as string));
}

const ALLOWED_TAGS = new Set(["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "strong", "em", "b", "i", "u", "br", "hr", "span", "div", "a", "img", "blockquote", "pre", "code", "dl", "dt", "dd", "colgroup", "col"]);
const ALLOWED_ATTRS = new Set(["href", "src", "alt", "title", "colspan", "rowspan", "class", "width", "height"]);

function sanitizeHtml(html: string): string {
  if (typeof window === "undefined") return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  function walk(node: Element): void {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (!ALLOWED_TAGS.has(tag)) { child.remove(); continue; }
      for (const attr of Array.from(child.attributes)) {
        const name = attr.name.toLowerCase();
        if (!ALLOWED_ATTRS.has(name)) { child.removeAttribute(attr.name); continue; }
        if ((name === "href" || name === "src") && /^(javascript|data|file|vbscript):/i.test(attr.value.trim())) {
          child.removeAttribute(attr.name);
        }
      }
      walk(child);
    }
  }
  walk(doc.body);
  return doc.body.innerHTML;
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
    return sanitizeHtml(result.value);
  }
  if (ext === "xlsx" || ext === "xls") {
    throw new Error("电子表格浏览器内预览已禁用，请下载文件后使用 Excel 或 LibreOffice 查看。");
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
    return sanitizeHtml(slides.length ? slides.join("") : "<p>未能在该演示文稿中提取到文本。</p>");
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
