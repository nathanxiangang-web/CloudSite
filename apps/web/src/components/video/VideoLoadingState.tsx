"use client";

import { Loader2 } from "lucide-react";

export function VideoLoadingState({ label = "正在加载视频…" }: { label?: string }) {
  return <div className="video-loading-state" role="status" aria-live="polite"><Loader2 className="spin" /><span>{label}</span></div>;
}
