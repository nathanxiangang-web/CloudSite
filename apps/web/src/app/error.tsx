"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const isStaleRuntime = /(?:chunkloaderror|loading chunk|dynamically imported module|cannot read properties of undefined.*(?:call|apply))/i.test(error.message);

  useEffect(() => {
    console.error(error);
    if (!isStaleRuntime) return;
    try {
      const key = "cloudsite:stale-runtime-reload-at";
      const previous = Number(sessionStorage.getItem(key) || 0);
      if (Date.now() - previous > 30_000) {
        sessionStorage.setItem(key, String(Date.now()));
        window.location.reload();
      }
    } catch { /* show the recovery page when storage is unavailable */ }
  }, [error, isStaleRuntime]);

  const retry = () => {
    if (isStaleRuntime) window.location.reload();
    else reset();
  };

  return (
    <div className="page state-page">
      <AlertCircle size={48} style={{ color: "#e24b57", margin: "0 auto 12px" }} />
      <strong style={{ color: "var(--blue)", fontSize: 48 }}>出错了</strong>
      <h1>页面加载失败</h1>
      <p>{isStaleRuntime ? "网站刚刚完成更新，刷新页面即可继续使用。" : "页面暂时无法加载，请稍后重试。"}</p>
      <button className="primary" onClick={retry}><RefreshCw size={16} />{isStaleRuntime ? "刷新页面" : "重试"}</button>
    </div>
  );
}
