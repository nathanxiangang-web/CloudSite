"use client";

import { useMemo, useState } from "react";
import { Download } from "lucide-react";
import { DownloadButton } from "@/components/DownloadButton";
import { handleMediaError, useVideoPlayer } from "./useVideoPlayer";
import { VideoControls } from "./VideoControls";
import { VideoErrorState } from "./VideoErrorState";
import { VideoLoadingState } from "./VideoLoadingState";
import { VideoCompatibilityHint } from "./VideoCompatibilityHint";

export function VideoPlayer({
  resourceId,
  name,
  gatewayUrl,
  mimeType,
  extension,
}: {
  resourceId: string;
  name: string;
  gatewayUrl: string;
  mimeType: string;
  extension: string;
}) {
  const [attempt, setAttempt] = useState(0);
  const player = useVideoPlayer(() => setAttempt((current) => current + 1));

  const src = useMemo(() => {
    const base = gatewayUrl || `/p/${resourceId}`;
    if (attempt === 0) return base;
    const separator = base.includes("?") ? "&" : "?";
    return `${base}${separator}refresh=1`;
  }, [gatewayUrl, resourceId, attempt]);

  const playing = player.phase === "playing";
  const download = <DownloadButton resourceId={resourceId} className="video-download" ariaLabel="下载文件" compact><Download />下载</DownloadButton>;

  return <div className="video-player-wrap">
    {player.error ? (
      <div className="video-player video-player-error"><VideoErrorState error={player.error} onRetry={player.reload} download={download} /></div>
    ) : (
      <div className="video-player">
        <video
          key={attempt}
          ref={player.ref}
          className="video-element"
          controls
          preload="metadata"
          playsInline
          tabIndex={0}
          aria-label={`播放视频 ${name}`}
          src={src}
          onLoadStart={() => { player.setPhase("loading_metadata"); player.setBuffering(false); }}
          onLoadedMetadata={(event) => {
            const el = event.currentTarget;
            player.setDuration(el.duration || 0);
            player.setVideoWidth(el.videoWidth || 0);
            player.setVideoHeight(el.videoHeight || 0);
            player.setPhase("ready");
          }}
          onError={(event) => {
            player.setError(handleMediaError(event.currentTarget.error));
            player.setPhase("error");
          }}
          onPlay={() => { player.setPhase("playing"); player.setError(null); }}
          onPause={() => player.setPhase("paused")}
          onWaiting={() => player.setBuffering(true)}
          onPlaying={() => { player.setBuffering(false); player.setPhase("playing"); }}
          onCanPlay={() => player.setBuffering(false)}
          onEnded={() => player.setPhase("ended")}
          onStalled={() => player.setBuffering(true)}
        />
        {(player.phase === "idle" || player.phase === "loading_metadata") && <VideoLoadingState label="正在加载视频…" />}
        {player.buffering && player.phase !== "idle" && player.phase !== "loading_metadata" && <VideoLoadingState label="缓冲中…" />}
      </div>
    )}
    <VideoControls
      playing={playing}
      onTogglePlay={player.togglePlay}
      playbackRate={player.playbackRate}
      onRateChange={player.setPlaybackRate}
      muted={player.muted}
      onToggleMute={player.toggleMuted}
      pipAvailable={player.pipAvailable}
      onTogglePiP={player.togglePictureInPicture}
      onToggleFullscreen={player.toggleFullscreen}
      duration={player.duration}
      videoWidth={player.videoWidth}
      videoHeight={player.videoHeight}
      onReload={player.reload}
      download={download}
    />
    <VideoCompatibilityHint extension={extension} />
  </div>;
}
