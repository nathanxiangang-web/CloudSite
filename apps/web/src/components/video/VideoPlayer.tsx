"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { VideoErrorState } from "./VideoErrorState";
import { VideoLoadingState } from "./VideoLoadingState";
import { formatTime, mapMediaError, VideoErrorKind } from "./video-utils";

type PlaybackProgress = {
  position_seconds: number;
  duration_seconds: number;
  completed: boolean;
  last_played_at?: string;
};

type VideoErrorInfo = { kind: VideoErrorKind; message: string };

export function VideoPlayer({
  resourceId,
  name,
  gatewayUrl,
}: {
  resourceId: string;
  name: string;
  gatewayUrl: string;
}) {
  const auth = useAuth();
  const ref = useRef<HTMLVideoElement | null>(null);
  const lastSavedAt = useRef(0);
  const lastSavedPosition = useRef(-1);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [buffering, setBuffering] = useState(false);
  const [error, setError] = useState<VideoErrorInfo | null>(null);
  const [resumeDismissed, setResumeDismissed] = useState(false);

  const progress = useQuery({
    queryKey: ["playback-progress", resourceId],
    queryFn: () => api<PlaybackProgress>(`/api/me/playback/${resourceId}`),
    enabled: Boolean(auth.data?.authenticated),
    retry: false,
  });

  const src = useMemo(() => {
    const base = gatewayUrl || `/p/${resourceId}`;
    if (attempt === 0) return base;
    return `${base}${base.includes("?") ? "&" : "?"}refresh=1`;
  }, [gatewayUrl, resourceId, attempt]);

  const saveProgress = useCallback((force = false) => {
    const video = ref.current;
    if (!auth.data?.authenticated || !video || !Number.isFinite(video.duration)) return;
    const position = Math.max(0, Math.floor(video.currentTime));
    const total = Math.max(0, Math.floor(video.duration));
    if (position < 5 && !video.ended) return;
    const now = Date.now();
    if (!force && now - lastSavedAt.current < 15_000) return;
    if (position === lastSavedPosition.current) return;
    lastSavedAt.current = now;
    lastSavedPosition.current = position;
    void fetch(`/api/me/playback/${resourceId}`, {
      method: "PUT",
      credentials: "same-origin",
      keepalive: force,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: position, duration_seconds: total }),
    }).catch(() => { /* 用户数据失败不阻塞播放器 */ });
  }, [auth.data?.authenticated, resourceId]);

  useEffect(() => {
    const onPageHide = () => saveProgress(true);
    const onVisibilityChange = () => { if (document.visibilityState === "hidden") saveProgress(true); };
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [saveProgress]);

  const reload = () => {
    setError(null);
    setBuffering(false);
    setLoading(true);
    setAttempt((current) => current + 1);
  };

  const resume = () => {
    const video = ref.current;
    const saved = progress.data?.position_seconds || 0;
    if (!video || saved < 5) return;
    video.currentTime = Math.min(saved, Math.max(0, video.duration - 1));
    setResumeDismissed(true);
    void video.play().catch(() => { /* 浏览器仍可让用户通过原生 controls 播放 */ });
  };

  const startOver = () => {
    if (ref.current) ref.current.currentTime = 0;
    lastSavedPosition.current = 0;
    setResumeDismissed(true);
    void api(`/api/me/playback/${resourceId}`, { method: "DELETE" }).catch(() => { /* 不阻塞播放 */ });
  };

  const showResume = !resumeDismissed && !progress.data?.completed && (progress.data?.position_seconds || 0) >= 5;

  return <div className="video-player-wrap">
    {error ? (
      <div className="video-player video-player-error"><VideoErrorState error={error} onRetry={reload} /></div>
    ) : (
      <div className="video-player">
        <video
          key={attempt}
          ref={ref}
          className="video-element"
          controls
          preload="metadata"
          playsInline
          aria-label={`播放视频 ${name}`}
          src={src}
          onLoadStart={() => { setLoading(true); setBuffering(false); }}
          onLoadedMetadata={() => setLoading(false)}
          onError={(event) => { setError(mapMediaError(event.currentTarget.error)); setLoading(false); }}
          onWaiting={() => setBuffering(true)}
          onPlaying={() => { setBuffering(false); setLoading(false); }}
          onCanPlay={() => { setBuffering(false); setLoading(false); }}
          onTimeUpdate={() => { if (Date.now() - lastSavedAt.current >= 5000) saveProgress(false); }}
          onPause={() => saveProgress(true)}
          onEnded={() => saveProgress(true)}
        />
        {loading && <VideoLoadingState label="正在加载视频…" />}
        {buffering && !loading && <VideoLoadingState label="缓冲中…" />}
      </div>
    )}
    {showResume && <div className="video-resume" role="status">
      <span>上次播放到 {formatTime(progress.data?.position_seconds || 0)}</span>
      <div><button type="button" className="primary" onClick={resume}>继续播放</button><button type="button" onClick={startOver}>从头播放</button></div>
    </div>}
  </div>;
}
