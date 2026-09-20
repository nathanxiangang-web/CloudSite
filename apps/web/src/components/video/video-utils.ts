export const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

export type VideoErrorKind =
  | "none"
  | "network_error"
  | "decode_error"
  | "source_not_supported"
  | "preview_gateway_error"
  | "resource_unavailable";

export type PlayerPhase =
  | "idle"
  | "loading_metadata"
  | "ready"
  | "playing"
  | "paused"
  | "buffering"
  | "ended"
  | "error";

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// MediaError 的 code 常量在不同 TS lib 版本间声明不稳定，直接用数值。
const MEDIA_ERR_ABORTED = 1;
const MEDIA_ERR_NETWORK = 2;
const MEDIA_ERR_DECODE = 3;
const MEDIA_ERR_SRC_NOT_SUPPORTED = 4;

export function mapMediaError(error: MediaError | null): { kind: VideoErrorKind; message: string } {
  if (!error) return { kind: "none", message: "" };
  switch (error.code) {
    case MEDIA_ERR_ABORTED:
      return { kind: "source_not_supported", message: "播放已中止" };
    case MEDIA_ERR_NETWORK:
      return { kind: "network_error", message: "视频加载失败，请稍后重试" };
    case MEDIA_ERR_DECODE:
      return { kind: "decode_error", message: "当前设备无法解码此视频" };
    case MEDIA_ERR_SRC_NOT_SUPPORTED:
      return { kind: "source_not_supported", message: "当前格式或编码不受支持" };
    default:
      return { kind: "decode_error", message: "视频播放出错" };
  }
}

export function compatibilityHint(extension: string): string {
  const ext = (extension || "").toLowerCase();
  if (ext === "mp4" || ext === "webm") return "MP4 / WebM 通常兼容较好。";
  if (ext === "mov" || ext === "mkv" || ext === "avi") return "MOV / MKV / AVI 能否播放取决于浏览器和内部编码。";
  return "视频能否播放取决于浏览器和内部编码。";
}

export function pictureInPictureSupported(): boolean {
  if (typeof document === "undefined") return false;
  return Boolean(document.pictureInPictureEnabled);
}

export function fullscreenSupported(video: HTMLVideoElement): boolean {
  return Boolean(video.requestFullscreen || (video as HTMLVideoElement & { webkitRequestFullscreen?: () => void }).webkitRequestFullscreen);
}

export function canPlayType(mimeType: string): "" | "maybe" | "probably" {
  if (typeof document === "undefined" || !mimeType) return "";
  const video = document.createElement("video");
  try {
    return video.canPlayType(mimeType) as "" | "maybe" | "probably";
  } catch {
    return "";
  }
}
