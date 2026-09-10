import type { QueryClient } from "@tanstack/react-query";

/**
 * 用户私人数据 query key 前缀集合。

 * 这些 key 的首段标识按用户隔离的私人数据，账户切换（登录/登出/注册）时
 * 应统一 remove，避免新账户看到旧账户残留数据。key 形如 [prefix, userId, ...]。
 */
export const USER_SCOPED_QUERY_KEY_PREFIXES = [
  "notifications",
  "favorite-status",
  "my-submissions",
  "user-library",
  "my-catalog-follows",
  "my-shares",
  "catalog-follow-status",
] as const;

/**
 * 移除所有用户私人数据 query 缓存。

 * 在登录、登出、注册成功后调用，确保账户切换不残留旧用户数据。
 * 用 removeQueries（而非 invalidateQueries）直接丢弃缓存，避免后台 refetch
 * 用旧 user_id 的 key 命中已登出用户的端点。
 */
export function clearUserScopedQueries(client: QueryClient): void {
  for (const prefix of USER_SCOPED_QUERY_KEY_PREFIXES) {
    client.removeQueries({ queryKey: [prefix] });
  }
}
