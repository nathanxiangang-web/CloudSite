"use client";

import Link from "next/link";
import { useSite } from "@/lib/site";

export function SiteFooter() {
  const year = new Date().getFullYear();
  const site = useSite();
  return <footer className="site-footer">
    <div className="site-footer-grid">
      <div className="site-footer-col">
        <h4>资源</h4>
        <Link href="/resources/software">资源库</Link>
        <Link href="/catalog">目录</Link>
        <Link href="/collections">精选</Link>
        <Link href="/cloud-download">云下载</Link>
      </div>
      <div className="site-footer-col">
        <h4>帮助</h4>
        <Link href="/about">使用指南</Link>
        <Link href="/submit">资源投稿</Link>
      </div>
      <div className="site-footer-col">
        <h4>关于</h4>
        <Link href="/about">关于我们</Link>
        <Link href="/terms">使用条款</Link>
        <Link href="/privacy">隐私政策</Link>
        {site.github_url && <a href={site.github_url} target="_blank" rel="noreferrer">GitHub</a>}
      </div>
    </div>
    <div className="site-footer-bottom">
      <span>{site.footer_text || `\u00a9 ${year} ${site.site_name} \u00b7 \u8ba9\u4e91\u4e0a\u8d44\u6e90\u89e6\u624b\u53ef\u53ca`}</span>
    </div>
  </footer>;
}
