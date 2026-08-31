"use client";

import { ReactNode, useEffect, useState } from "react";

type RateLimitResponse = {
  code: "DOWNLOAD_RATE_LIMITED";
  message: string;
  retry_after: number;
  blocked_until: string;
};

export function DownloadButton({
  resourceId,
  children,
  className,
  ariaLabel = "立即下载",
  compact = false,
}: {
  resourceId: string;
  children: ReactNode;
  className?: string;
  ariaLabel?: string;
  compact?: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!blockedUntil) return;
    const tick = () => {
      const next = Math.max(0, Math.ceil((blockedUntil - Date.now()) / 1000));
      setRemaining(next);
      if (next === 0) setBlockedUntil(null);
    };
    tick();
    const timer = window.setInterval(tick, 250);
    return () => window.clearInterval(timer);
  }, [blockedUntil]);

  async function startDownload() {
    if (remaining > 0 || pending) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch(`/d/${encodeURIComponent(resourceId)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (response.status === 401 || response.status === 403) {
        const payload = await response.json().catch(() => ({})) as { detail?: { code?: string } };
        if (["AUTH_REQUIRED", "SESSION_INVALID", "SESSION_REVOKED", "SESSION_EXPIRED", "USER_DELETED", "USER_DISABLED"].includes(payload.detail?.code || "")) {
          const next = `${window.location.pathname}${window.location.search}`;
          window.location.assign(`/login?next=${encodeURIComponent(next)}`);
          return;
        }
      }
      if (response.status === 429) {
        const payload = await response.json() as RateLimitResponse;
        const retryAfter = Math.max(1, Number(payload.retry_after) || Number(response.headers.get("Retry-After")) || 60);
        setRemaining(retryAfter);
        setBlockedUntil(Date.now() + retryAfter * 1000);
        return;
      }
      const contentType = response.headers.get("content-type") || "";
      if (response.ok && contentType.includes("application/json")) {
        const payload = await response.json() as { url?: string };
        if (payload.url) {
          window.location.assign(payload.url);
          return;
        }
      }
      if (response.redirected && response.url) {
        window.location.assign(response.url);
        return;
      }
      setError("下载入口暂时不可用，请稍后重试");
    } catch {
      setError("网络连接异常，请稍后重试");
    } finally {
      setPending(false);
    }
  }

  const waitLabel = remaining > 0 ? `请等待 ${remaining} 秒` : pending ? "正在准备下载…" : ariaLabel;
  return <>
    <button
      type="button"
      className={className}
      aria-label={waitLabel}
      title={waitLabel}
      disabled={pending || remaining > 0}
      onClick={startDownload}
    >
      {compact ? children : remaining > 0 ? waitLabel : pending ? "正在准备下载…" : children}
    </button>
    {(remaining > 0 || error) && <div className={`download-toast${error ? " error" : ""}`} role="status" aria-live="polite">
      <strong>{error ? "下载失败" : "下载过于频繁"}</strong>
      <span>{error || `请 ${remaining} 秒后再试`}</span>
    </div>}
  </>;
}
