"use client";

import { useQuery } from "@tanstack/react-query";
import { Cloud } from "lucide-react";
import { api, StorageInfo } from "@/lib/api";
import { useHydrated } from "./useHydrated";

export function StorageInfoCard() {
  const hydrated = useHydrated();
  const query = useQuery({ queryKey: ["storage-info"], queryFn: () => api<StorageInfo>("/api/storage/info"), staleTime: 5 * 60 * 1000, refetchInterval: 10 * 60 * 1000 });
  if (!hydrated || query.isLoading) return <div className="storage"><small><Cloud size={13} />当前网盘</small><strong>读取中…</strong></div>;
  if (query.error) return <div className="storage"><small><Cloud size={13} />当前网盘</small><strong title={query.error.message}>状态不可用</strong><button type="button" onClick={() => query.refetch()}>重试</button></div>;
  const name = query.data?.primary || "未配置";
  return <div className="storage"><small><Cloud size={13} />当前网盘</small><strong title={name}>{name}</strong></div>;
}
