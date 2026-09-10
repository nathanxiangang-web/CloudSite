"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { api } from "./api";

export type ShareDuration = "5m" | "1h" | "6h" | "24h" | "7d" | "permanent";

export type PresentationNavigationItem = { label: string; href: string; sort_order: number };
export type PresentationThemeTokens = { accent_color: string; card_radius: number };
export type SitePresentation = {
  enabled: boolean;
  preset: string;
  theme_tokens: PresentationThemeTokens;
  navigation: PresentationNavigationItem[];
};

export type PublicSiteSettings = {
  site_name: string;
  site_tagline: string;
  hero_title: string;
  hero_subtitle: string;
  footer_text: string;
  submission_email: string;
  github_url: string;
  registration_enabled: boolean;
  default_share_duration: ShareDuration;
  version: string;
  content_counts?: Record<string, number>;
  presentation?: SitePresentation;
};

export const SITE_QUERY_KEY = ["public-site"] as const;

const fallback: PublicSiteSettings = {
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
  presentation: {
    enabled: false,
    preset: "software",
    theme_tokens: { accent_color: "#2563eb", card_radius: 12 },
    navigation: [
      { label: "首页", href: "/", sort_order: 0 },
      { label: "资源库", href: "/resources/software", sort_order: 1 },
      { label: "目录", href: "/catalog", sort_order: 2 },
      { label: "精选", href: "/collections", sort_order: 3 },
      { label: "最近更新", href: "/resources/file", sort_order: 4 },
      { label: "使用指南", href: "/about", sort_order: 5 },
    ],
  },
};

const SiteContext = createContext<PublicSiteSettings>(fallback);

export function SiteProvider({ children, initialSite }: { children: React.ReactNode; initialSite?: PublicSiteSettings }) {
  const query = useQuery({
    queryKey: SITE_QUERY_KEY,
    queryFn: () => api<PublicSiteSettings>("/api/site"),
    staleTime: 60_000,
    initialData: initialSite,
  });
  return <SiteContext.Provider value={query.data ?? fallback}>{children}</SiteContext.Provider>;
}

export function useSite() {
  return useContext(SiteContext);
}
