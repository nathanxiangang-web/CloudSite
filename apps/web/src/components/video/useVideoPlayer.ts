"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mapMediaError, PlayerPhase, VideoErrorKind } from "./video-utils";

const RATE_KEY = "cloudsite:video:playbackRate";
const VOLUME_KEY = "cloudsite:video:volume";
const MUTED_KEY = "cloudsite:video:muted";

function readStoredNumber(key: string): number | null {
  if (typeof window === "undefined") return null;
  const value = Number(window.localStorage.getItem(key));
  return Number.isFinite(value) ? value : null;
}

export type VideoErrorInfo = { kind: VideoErrorKind; message: string };

export function useVideoPlayer(onReload: () => void) {
  const ref = useRef<HTMLVideoElement | null>(null);

  const [phase, setPhase] = useState<PlayerPhase>("idle");
  const [error, setError] = useState<VideoErrorInfo | null>(null);
  const [playbackRate, setPlaybackRateState] = useState<number>(() => readStoredNumber(RATE_KEY) ?? 1);
  const [volume, setVolumeState] = useState<number>(() => readStoredNumber(VOLUME_KEY) ?? 1);
  const [muted, setMutedState] = useState<boolean>(() => typeof window !== "undefined" && window.localStorage.getItem(MUTED_KEY) === "1");
  const [duration, setDuration] = useState(0);
  const [videoWidth, setVideoWidth] = useState(0);
  const [videoHeight, setVideoHeight] = useState(0);
  const [buffering, setBuffering] = useState(false);
  const [pipAvailable, setPipAvailable] = useState(false);

  useEffect(() => {
    setPipAvailable(Boolean(document.pictureInPictureEnabled));
  }, []);

  const video = ref.current;

  const setPlaybackRate = useCallback((rate: number) => {
    setPlaybackRateState(rate);
    try { window.localStorage.setItem(RATE_KEY, String(rate)); } catch { /* ignore */ }
    if (ref.current) ref.current.playbackRate = rate;
  }, []);

  const setVolume = useCallback((value: number) => {
    const clamped = Math.max(0, Math.min(1, value));
    setVolumeState(clamped);
    try { window.localStorage.setItem(VOLUME_KEY, String(clamped)); } catch { /* ignore */ }
    if (ref.current) { ref.current.volume = clamped; ref.current.muted = clamped === 0; }
  }, []);

  const toggleMuted = useCallback(() => {
    setMutedState((current) => {
      const next = !current;
      try { window.localStorage.setItem(MUTED_KEY, next ? "1" : "0"); } catch { /* ignore */ }
      if (ref.current) ref.current.muted = next;
      return next;
    });
  }, []);

  const togglePlay = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    if (el.paused) void el.play().catch(() => { /* autoplay blocked; ignore */ });
    else el.pause();
  }, []);

  const seekBy = useCallback((seconds: number) => {
    const el = ref.current;
    if (!el || !Number.isFinite(el.duration)) return;
    el.currentTime = Math.max(0, Math.min(el.duration, el.currentTime + seconds));
  }, []);

  const togglePictureInPicture = useCallback(async () => {
    const el = ref.current;
    if (!el) return;
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else if (el.requestPictureInPicture) await el.requestPictureInPicture();
    } catch { /* ignore */ }
  }, []);

  const toggleFullscreen = useCallback(async () => {
    const el = ref.current as (HTMLVideoElement & { webkitRequestFullscreen?: () => void }) | null;
    if (!el) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (el.requestFullscreen) await el.requestFullscreen();
      else el.webkitRequestFullscreen?.();
    } catch { /* ignore */ }
  }, []);

  const reload = useCallback(() => {
    setError(null);
    setBuffering(false);
    setPhase("loading_metadata");
    onReload();
  }, [onReload]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.playbackRate = playbackRate;
    el.volume = volume;
    el.muted = muted;
  }, [playbackRate, volume, muted, video]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName)) return;
      switch (event.key) {
        case " ":
        case "k":
        case "K":
          event.preventDefault();
          togglePlay();
          break;
        case "ArrowLeft":
          event.preventDefault();
          seekBy(-5);
          break;
        case "ArrowRight":
          event.preventDefault();
          seekBy(5);
          break;
        case "m":
        case "M":
          event.preventDefault();
          toggleMuted();
          break;
        case "f":
        case "F":
          event.preventDefault();
          void toggleFullscreen();
          break;
      }
    };
    el.addEventListener("keydown", onKeyDown);
    return () => el.removeEventListener("keydown", onKeyDown);
  }, [video, togglePlay, seekBy, toggleMuted, toggleFullscreen]);

  return {
    ref,
    phase,
    error,
    playbackRate,
    volume,
    muted,
    duration,
    videoWidth,
    videoHeight,
    buffering,
    pipAvailable,
    setPhase,
    setError,
    setDuration,
    setVideoWidth,
    setVideoHeight,
    setBuffering,
    setPlaybackRate,
    setVolume,
    toggleMuted,
    togglePlay,
    togglePictureInPicture,
    toggleFullscreen,
    reload,
  };
}

export function handleMediaError(error: MediaError | null): VideoErrorInfo {
  return mapMediaError(error);
}
