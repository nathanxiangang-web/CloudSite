"use client";

import { RefreshCw, Video } from "lucide-react";
import { VideoErrorKind } from "./video-utils";

type VideoErrorInfo = { kind: VideoErrorKind; message: string };

export function VideoErrorState({ error, onRetry }: { error: VideoErrorInfo; onRetry: () => void }) {
  const isDecode = error.kind === "decode_error";
  return <div className="video-error-state" role="alert">
    <Video />
    <strong>{error.message}</strong>
    {isDecode && <p>文件本身可能正常，但当前浏览器、系统媒体组件或硬件解码器可能不支持其编码。</p>}
    <div className="video-error-actions">
      <button type="button" onClick={onRetry}><RefreshCw />重新尝试</button>
    </div>
  </div>;
}
