"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Pin, Info, CheckCircle2, AlertTriangle, AlertCircle, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Notification = {
  id: number;
  user_id: number | null;
  title: string;
  body: string;
  level: "info" | "success" | "warning" | "important";
  pinned: boolean;
  enabled: boolean;
  source: string;
  published_at: string;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
};

const LAST_READ_KEY = "cloudsite:notifications-last-read-at";

const levelIcon: Record<Notification["level"], typeof Info> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  important: AlertCircle,
};

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = Date.now();
  const diff = now - date.getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

export function NotificationBell() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [lastReadAt, setLastReadAt] = useState<string>("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLastReadAt(localStorage.getItem(LAST_READ_KEY) ?? "");
  }, []);

  useEffect(() => {
    if (!open) return;
    const now = new Date().toISOString();
    localStorage.setItem(LAST_READ_KEY, now);
    setLastReadAt(now);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<{ items: Notification[] }>("/api/notifications"),
    staleTime: 60_000,
    retry: false,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/api/notifications/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const items = query.data?.items ?? [];
  const unreadCount = lastReadAt
    ? items.filter((item) => new Date(item.published_at) > new Date(lastReadAt)).length
    : items.length;

  return <div className="notification-bell" ref={ref}>
    <button className="topbar-icon" title="站内通知" aria-label="站内通知" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      <Bell />
      {unreadCount > 0 && <span className="notification-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>}
    </button>
    {open && <div className="notification-popover" role="dialog" aria-label="站内通知">
      <div className="notification-popover-head"><span>站内通知</span>{unreadCount > 0 && <small>{unreadCount} 条未读</small>}</div>
      {query.isLoading ? <div className="notification-empty">加载中…</div>
        : query.error ? <div className="notification-empty">未能获取通知</div>
        : items.length === 0 ? <div className="notification-empty">暂无通知</div>
        : <ul className="notification-list">
          {items.map((item) => {
            const Icon = levelIcon[item.level] ?? Info;
            const isNew = !lastReadAt || new Date(item.published_at) > new Date(lastReadAt);
            return <li key={item.id} className={`notification-item level-${item.level}${isNew ? " unread" : ""}`}>
              <Icon size={16} className="notification-item-icon" />
              <div className="notification-item-body">
                <div className="notification-item-title">{item.pinned && <Pin size={12} className="notification-pin" />}{item.title}</div>
                {item.body && <p className="notification-item-text">{item.body}</p>}
                <time className="notification-item-time">{formatTime(item.published_at)}</time>
              </div>
              {item.user_id !== null && <button className="notification-item-delete" title="删除该通知" aria-label="删除该通知" disabled={remove.isPending} onClick={() => remove.mutate(item.id)}><X size={14} /></button>}
            </li>;
          })}
        </ul>}
    </div>}
  </div>;
}
