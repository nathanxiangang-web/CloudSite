"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type PublicUser = {
  id: number;
  username: string;
  status: "active" | "disabled";
  created_at: string;
  last_login_at: string | null;
  password_changed_at: string | null;
};

export type AuthState = {
  authenticated: boolean;
  user: PublicUser | null;
};

export const AUTH_QUERY_KEY = ["public-auth"] as const;

export function useAuth() {
  return useQuery({
    queryKey: AUTH_QUERY_KEY,
    queryFn: () => api<AuthState>("/api/auth/me"),
    staleTime: 15_000,
  });
}
