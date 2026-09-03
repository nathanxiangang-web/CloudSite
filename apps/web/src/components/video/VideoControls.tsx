"use client";

import { Maximize, Pause, PictureInPicture2, Play, RefreshCw, Volume2, VolumeX } from "lucide-react";
import { PLAYBACK_RATES, formatTime } from "./video-utils";

export function VideoControls({
  playing,
  onTogglePlay,
  playbackRate,
  onRateChange,
  muted,
  onToggleMute,
  pipAvailable,
  onTogglePiP,
  onToggleFullscreen,
  duration,
  videoWidth,
  videoHeight,
  onReload,
  download,
}: {
  playing: boolean;
  onTogglePlay: () => void;
  playbackRate: number;
  onRateChange: (rate: number) => void;
  muted: boolean;
  onToggleMute: () => void;
  pipAvailable: boolean;
  onTogglePiP: () => void;
  onToggleFullscreen: () => void;
  duration: number;
  videoWidth: number;
  videoHeight: number;
  onReload: () => void;
  download?: React.ReactNode;
}) {
  const resolution = videoWidth && videoHeight ? `${videoWidth}×${videoHeight}` : "";
  return <div className="video-controls">
    <div className="video-controls-left">
      <button type="button" className="video-ctrl" onClick={onTogglePlay} title={playing ? "暂停" : "播放"}>{playing ? <Pause /> : <Play />}</button>
      <label className="video-speed">
        <select value={playbackRate} onChange={(event) => onRateChange(Number(event.target.value))} aria-label="播放速度">
          {PLAYBACK_RATES.map((rate) => <option key={rate} value={rate}>{rate}×</option>)}
        </select>
      </label>
      <button type="button" className="video-ctrl" onClick={onToggleMute} title={muted ? "取消静音" : "静音"}>{muted ? <VolumeX /> : <Volume2 />}</button>
      {pipAvailable && <button type="button" className="video-ctrl" onClick={onTogglePiP} title="画中画"><PictureInPicture2 /></button>}
      <button type="button" className="video-ctrl" onClick={onToggleFullscreen} title="全屏"><Maximize /></button>
      <button type="button" className="video-ctrl" onClick={onReload} title="重新加载"><RefreshCw /></button>
    </div>
    <div className="video-controls-meta">
      {duration > 0 && <span>{formatTime(duration)}</span>}
      {resolution && <span>{resolution}</span>}
      {download}
    </div>
  </div>;
}
