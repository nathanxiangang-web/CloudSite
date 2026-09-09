"use client";

import { useQuery } from "@tanstack/react-query";
import { Cloud } from "lucide-react";
import { api, StorageInfo } from "@/lib/api";
import { useHydrated } from "./useHydrated";

export function StorageInfoCard() {
  const hydrated = useHydrated();
  const query = useQuery({ queryKey: ["storage-info"], queryFn: () => api<StorageInfo>("/api/storage/info"), staleTime: 5 * 60 * 1000, refetchInterval: 10 * 60 * 1000 });
  const name = hydrated ? query.data?.primary || "网盘" : "网盘";
  return <div className="storage"><small><Cloud size={13} />当前网盘</small><strong title={name}>{name}</strong></div>;
}
