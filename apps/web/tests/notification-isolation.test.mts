import assert from "node:assert/strict";
import test from "node:test";

import {
  getLastReadAt,
  lastReadKey,
  NOTIFICATION_LAST_READ_PREFIX,
  setLastReadAt,
  type StorageLike,
} from "../src/lib/notification-read-state.ts";

function makeStorage(): StorageLike {
  const store = new Map<string, string>();
  return {
    getItem(key: string): string | null {
      return store.has(key) ? (store.get(key) as string) : null;
    },
    setItem(key: string, value: string): void {
      store.set(key, value);
    },
  };
}


test("lastReadKey 按用户拼接，不同用户 key 不同", () => {
  assert.equal(lastReadKey(1), `${NOTIFICATION_LAST_READ_PREFIX}:1`);
  assert.equal(lastReadKey(2), `${NOTIFICATION_LAST_READ_PREFIX}:2`);
  assert.notEqual(lastReadKey(1), lastReadKey(2));
});


test("两个用户的通知已读状态独立存储互不干扰", () => {
  const storage = makeStorage();
  setLastReadAt(1, "2026-09-10T10:00:00Z", storage);
  setLastReadAt(2, "2026-09-10T11:00:00Z", storage);
  assert.equal(getLastReadAt(1, storage), "2026-09-10T10:00:00Z");
  assert.equal(getLastReadAt(2, storage), "2026-09-10T11:00:00Z");
  // 用户 2 更新不影响用户 1
  setLastReadAt(2, "2026-09-10T12:00:00Z", storage);
  assert.equal(getLastReadAt(1, storage), "2026-09-10T10:00:00Z");
  assert.equal(getLastReadAt(2, storage), "2026-09-10T12:00:00Z");
});


test("账户切换后不残留旧用户已读状态：新用户读到空而非旧用户时间", () => {
  const storage = makeStorage();
  setLastReadAt(1, "2026-09-10T10:00:00Z", storage);
  // 切换到用户 2（从未读过）
  assert.equal(getLastReadAt(2, storage), "");
  // 用户 1 的数据仍在自己的 key 下，但用户 2 不会读到它
  assert.equal(getLastReadAt(1, storage), "2026-09-10T10:00:00Z");
});


test("未登录时不读写 storage，避免全局 key 残留", () => {
  const storage = makeStorage();
  setLastReadAt(null, "2026-09-10T10:00:00Z", storage);
  setLastReadAt(undefined, "2026-09-10T10:00:00Z", storage);
  assert.equal(getLastReadAt(null, storage), "");
  assert.equal(getLastReadAt(undefined, storage), "");
  // storage 不应被写入任何条目
  assert.equal(storage.getItem(lastReadKey(1)), null);
});


test("storage 异常时静默降级不抛错", () => {
  const throwingStorage: StorageLike = {
    getItem(): string | null {
      throw new Error("disabled");
    },
    setItem(): void {
      throw new Error("disabled");
    },
  };
  assert.doesNotThrow(() => setLastReadAt(1, "x", throwingStorage));
  assert.doesNotThrow(() => {
    const v = getLastReadAt(1, throwingStorage);
    assert.equal(v, "");
  });
});
