"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AUTH_FUSE_EVENT } from "@/lib/api";
import { AUTH_QUERY_KEY } from "@/lib/auth";
import { SiteProvider } from "@/lib/site";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1 } } }));
  useEffect(() => {
    const clearAuthState = () => client.removeQueries({ queryKey: AUTH_QUERY_KEY });
    window.addEventListener(AUTH_FUSE_EVENT, clearAuthState);
    return () => window.removeEventListener(AUTH_FUSE_EVENT, clearAuthState);
  }, [client]);
  return <QueryClientProvider client={client}><SiteProvider>{children}</SiteProvider></QueryClientProvider>;
}
