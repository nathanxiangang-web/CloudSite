"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return (
    <div className="page state-page">
      <AlertCircle size={48} style={{ color: "#e24b57", margin: "0 auto 12px" }} />
      <strong style={{ color: "var(--blue)", fontSize: 48 }}>出错了</strong>
      <h1>页面加载失败</h1>
      <p>{error.message || "发生未知错误，请稍后重试。"}</p>
      <button className="primary" onClick={reset}><RefreshCw size={16} />重试</button>
    </div>
  );
}
