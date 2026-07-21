import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "./authStore";
import type { User } from "@/types";

const TOKEN_KEY = "step_jwt";

function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

// jwt-decode only base64-decodes the payload (no signature check), so a fake
// three-segment token is sufficient to exercise decodeTokenToUser.
function makeToken(payload: Record<string, unknown>): string {
  return `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url(payload)}.sig`;
}

const basePayload = (over: Record<string, unknown> = {}) => ({
  sub: "u-1",
  username: "test_spv",
  full_name: "Test SPV",
  role: "spv",
  exp: Math.floor(Date.now() / 1000) + 3600,
  ...over,
});

beforeEach(() => {
  localStorage.clear();
  useAuthStore.setState({ user: null, token: null, isAuthenticated: false });
});

describe("authStore", () => {
  it("login persists the token and marks the session authenticated", () => {
    const token = makeToken(basePayload());
    const user = { user_id: "u-1", username: "test_spv", role: "spv" } as User;
    useAuthStore.getState().login(token, user);

    const s = useAuthStore.getState();
    expect(s.isAuthenticated).toBe(true);
    expect(s.token).toBe(token);
    expect(localStorage.getItem(TOKEN_KEY)).toBe(token);
  });

  it("logout clears both state and storage", () => {
    useAuthStore.getState().login(makeToken(basePayload()), { username: "x" } as User);
    useAuthStore.getState().logout();

    const s = useAuthStore.getState();
    expect(s.isAuthenticated).toBe(false);
    expect(s.token).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("rehydrate maps a valid token's claims onto the user", () => {
    localStorage.setItem(
      TOKEN_KEY,
      makeToken(basePayload({ role: "dm", sub: "u-9", territory: "JKT" })),
    );
    useAuthStore.getState().rehydrate();

    const s = useAuthStore.getState();
    expect(s.isAuthenticated).toBe(true);
    expect(s.user?.role).toBe("dm");
    expect(s.user?.user_id).toBe("u-9");
    expect(s.user?.territory).toBe("JKT");
  });

  it("rehydrate rejects an expired token and clears storage", () => {
    localStorage.setItem(
      TOKEN_KEY,
      makeToken(basePayload({ exp: Math.floor(Date.now() / 1000) - 10 })),
    );
    useAuthStore.getState().rehydrate();

    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("rehydrate rejects a malformed token without throwing", () => {
    localStorage.setItem(TOKEN_KEY, "not-a-jwt");
    expect(() => useAuthStore.getState().rehydrate()).not.toThrow();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });
});
