import type { Metadata } from "next";
import { cache } from "react";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { PublicSiteSettings } from "@/lib/site";

const apiBase = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

const fallbackSite: PublicSiteSettings = {
  site_name: "CloudSite",
  site_tagline: "",
  hero_title: "把网盘变成好看的资源网站",
  hero_subtitle: "",
  footer_text: "",
  submission_email: "",
  github_url: "",
  registration_enabled: true,
  default_share_duration: "24h",
  version: "",
  content_counts: {},
};

const getSite = cache(async (): Promise<PublicSiteSettings> => {
  try {
    const res = await fetch(`${apiBase}/api/site`, { next: { revalidate: 300 } });
    if (res.ok) return await res.json();
  } catch { /* fallback */ }
  return fallbackSite;
});

export async function generateMetadata(): Promise<Metadata> {
  const site = await getSite();
  return { title: site.site_name, description: site.hero_subtitle || site.site_tagline || "把网盘变成好看的资源网站" };
}

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const initialSite = await getSite();
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `(function(){try{var t=localStorage.getItem('cloudsite-theme');if(!t)t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';document.documentElement.setAttribute('data-theme',t);}catch(e){}})();` }} />
      </head>
      <body><Providers initialSite={initialSite}>{children}</Providers></body>
    </html>
  );
}
