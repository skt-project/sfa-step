import { create } from "zustand";
import { jwtDecode } from "jwt-decode";
import type { User } from "@/types";
import { api, clearToken, getToken, saveToken } from "@/api/client";

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (token: string, user: User) => void;
  logout: () => void;
  rehydrate: () => void;
}

function decodeTokenToUser(token: string): User | null {
  try {
    const decoded = jwtDecode<User & { exp: number; sub: string }>(token);
    if (decoded.exp * 1000 < Date.now()) {
      clearToken();
      return null;
    }
    return {
      user_id: decoded.sub,
      username: decoded.username,
      full_name: decoded.full_name ?? decoded.username,
      role: decoded.role,
      email: decoded.email ?? null,
      territory: decoded.territory,
      distributor_code: decoded.distributor_code,
      brand_group: decoded.brand_group ?? null,
      salesman_sk: decoded.salesman_sk ?? null,
      is_active: decoded.is_active ?? true,
    };
  } catch {
    clearToken();
    return null;
  }
}

// Initialize synchronously from localStorage so isAuthenticated is correct
// on the very first render — no useEffect / rehydrate race condition.
function loadInitialState(): Pick<AuthState, "token" | "user" | "isAuthenticated"> {
  const token = getToken();
  if (!token) return { token: null, user: null, isAuthenticated: false };
  const user = decodeTokenToUser(token);
  if (!user) return { token: null, user: null, isAuthenticated: false };
  return { token, user, isAuthenticated: true };
}

export const useAuthStore = create<AuthState>((set) => ({
  ...loadInitialState(),

  login: (token, user) => {
    saveToken(token);
    set({ token, user, isAuthenticated: true });
  },

  logout: () => {
    // E2E-14: revoke the session server-side (best-effort — the interceptor won't
    // redirect on this call's own 401), then clear the local token.
    api.post("/auth/logout").catch(() => { /* best-effort */ });
    clearToken();
    set({ token: null, user: null, isAuthenticated: false });
  },

  // Kept for backward compatibility; no longer needed since store initializes
  // synchronously.  Safe to call — it re-reads localStorage.
  rehydrate: () => {
    const token = getToken();
    if (!token) {
      set({ token: null, user: null, isAuthenticated: false });
      return;
    }
    const user = decodeTokenToUser(token);
    if (!user) {
      set({ token: null, user: null, isAuthenticated: false });
      return;
    }
    set({ token, user, isAuthenticated: true });
  },
}));
