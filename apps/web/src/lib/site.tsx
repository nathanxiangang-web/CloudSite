"use client";

import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { api } from "./api";

export type ShareDuration = "5m" | "1h" | "6h" | "24h" | "7d" | "permanent";

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
};

const SiteContext = createContext<PublicSiteSettings>(fallback);

export function SiteProvider({ children }: { children: React.ReactNode }) {
  const query = useQuery({
    queryKey: SITE_QUERY_KEY,
    queryFn: () => api<PublicSiteSettings>("/api/site"),
    staleTime: 60_000,
  });
  return <SiteContext.Provider value={query.data ?? fallback}>{children}</SiteContext.Provider>;
}

export function useSite() {
  return useContext(SiteContext);
}
