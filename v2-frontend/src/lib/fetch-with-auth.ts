import { getToken, clearAuth } from "./auth";
import { refreshAccessToken } from "./api";

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  // Deduplicate concurrent refresh attempts
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    const result = await refreshAccessToken();
    return result !== null;
  })();

  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

/**
 * Wrapper around fetch that:
 * 1. Adds Authorization header
 * 2. On 401, attempts to refresh the access token
 * 3. Retries the original request once
 * 4. If still 401, clears auth and redirects to /login
 */
export async function fetchWithAuth(
  url: string,
  options?: RequestInit & { timeout?: number },
): Promise<Response> {
  const token = getToken();
  const timeout = options?.timeout ?? 30000;

  const headers = new Headers(options?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  // Skip timeout for SSE streams
  const isSSE = headers.get("Accept") === "text/event-stream" ||
    url.includes("/stream");
  const controller = !isSSE && timeout > 0 ? new AbortController() : null;
  const timer = controller
    ? setTimeout(() => controller.abort(), timeout)
    : null;

  try {
    const res = await fetch(url, {
      ...options,
      headers,
      signal: controller?.signal ?? options?.signal,
    });

    if (res.status !== 401) return res;

    // Try to refresh
    const refreshed = await tryRefresh();
    if (!refreshed) {
      clearAuth();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      return res;
    }

    // Retry with new token
    const newToken = getToken();
    const retryHeaders = new Headers(options?.headers);
    if (newToken) {
      retryHeaders.set("Authorization", `Bearer ${newToken}`);
    }

    const retryRes = await fetch(url, {
      ...options,
      headers: retryHeaders,
      signal: controller?.signal ?? options?.signal,
    });

    if (retryRes.status === 401) {
      clearAuth();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }

    return retryRes;
  } finally {
    if (timer) clearTimeout(timer);
  }
}
