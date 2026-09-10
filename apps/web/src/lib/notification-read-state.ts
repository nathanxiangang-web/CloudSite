/**
 * 通知已读时间按用户隔离的纯函数。

 * key 形如 `cloudsite:notifications-last-read-at:${userId}`，不同用户互不干扰。
 * 未登录（userId 为 null/undefined）时不读写 storage，避免全局 key 残留。
 * storage 参数默认取 globalThis.localStorage，测试可注入 mock。
 */
export const NOTIFICATION_LAST_READ_PREFIX = "cloudsite:notifications-last-read-at";

export type StorageLike = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};

function resolveStorage(storage?: StorageLike | null): StorageLike | null {
  if (storage) return storage;
  if (typeof globalThis !== "undefined" && globalThis.localStorage) return globalThis.localStorage;
  return null;
}

export function lastReadKey(userId: number | string | null | undefined): string {
  return `${NOTIFICATION_LAST_READ_PREFIX}:${userId}`;
}

export function getLastReadAt(
  userId: number | string | null | undefined,
  storage?: StorageLike | null,
): string {
  if (userId === null || userId === undefined) return "";
  const s = resolveStorage(storage);
  if (!s) return "";
  try {
    return s.getItem(lastReadKey(userId)) ?? "";
  } catch {
    return "";
  }
}

export function setLastReadAt(
  userId: number | string | null | undefined,
  value: string,
  storage?: StorageLike | null,
): void {
  if (userId === null || userId === undefined) return;
  const s = resolveStorage(storage);
  if (!s) return;
  try {
    s.setItem(lastReadKey(userId), value);
  } catch {
    /* quota 或禁用：静默忽略 */
  }
}
