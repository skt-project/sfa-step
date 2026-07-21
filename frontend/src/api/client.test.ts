import { describe, it, expect, beforeEach } from "vitest";
import { api, saveToken, getToken, clearToken } from "./client";

const TOKEN_KEY = "step_jwt";

// axios stores registered interceptors on `.handlers`; there is exactly one of
// each in this module, so index 0 is the app's interceptor.
function requestInterceptor(config: Record<string, unknown>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (api.interceptors.request as any).handlers[0].fulfilled(config);
}
function responseRejection(err: unknown) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (api.interceptors.response as any).handlers[0].rejected(err);
}

beforeEach(() => {
  localStorage.clear();
});

describe("token helpers", () => {
  it("round-trips a token through localStorage under the step_jwt key", () => {
    saveToken("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("abc.def.ghi");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

describe("request interceptor", () => {
  it("attaches a Bearer header when a token is stored", () => {
    saveToken("tok123");
    const out = requestInterceptor({ headers: {} }) as { headers: Record<string, string> };
    expect(out.headers.Authorization).toBe("Bearer tok123");
  });

  it("sends no Authorization header when there is no token", () => {
    const out = requestInterceptor({ headers: {} }) as { headers: Record<string, string> };
    expect(out.headers.Authorization).toBeUndefined();
  });
});

describe("response interceptor", () => {
  it("clears the stored token on a 401 (session invalidation)", async () => {
    saveToken("tok");
    await expect(responseRejection({ response: { status: 401 } })).rejects.toBeDefined();
    expect(getToken()).toBeNull();
  });

  it("leaves the token intact on non-401 errors", async () => {
    saveToken("tok");
    await expect(responseRejection({ response: { status: 500 } })).rejects.toBeDefined();
    expect(getToken()).toBe("tok");
  });
});
