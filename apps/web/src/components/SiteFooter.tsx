import Link from "next/link";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return <footer className="site-footer"><span>© {year} CloudSite · 让云上资源触手可及</span><span><Link href="/about">关于我们</Link><Link href="/submit">资源投稿</Link><Link href="/terms">使用条款</Link><Link href="/privacy">隐私政策</Link><a href="https://github.com/nathanxiangang-web/CloudSite" target="_blank" rel="noreferrer">GitHub</a></span></footer>;
}
