"use client";

import Link from "next/link";
import { useSite } from "@/lib/site";

export function SiteFooter() {
  const year = new Date().getFullYear();
  const site = useSite();
  return <footer className="site-footer"><span>{site.footer_text || `© ${year} ${site.site_name} · 让云上资源触手可及`}</span><span><Link href="/about">关于我们</Link><Link href="/submit">资源投稿</Link><Link href="/terms">使用条款</Link><Link href="/privacy">隐私政策</Link>{site.github_url && <a href={site.github_url} target="_blank" rel="noreferrer">GitHub</a>}</span></footer>;
}
