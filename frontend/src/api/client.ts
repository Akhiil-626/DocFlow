import createClient from 'openapi-fetch';
import type { paths } from './schema';

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

let inMemoryToken: string | null = null;
let onAuthFailureCallback: (() => void) | null = null;
let refreshPromise: Promise<string | null> | null = null;

export function getAccessToken(): string | null {
  return inMemoryToken;
}

export function setAccessToken(token: string | null): void {
  inMemoryToken = token;
}

export function setOnAuthFailure(callback: (() => void) | null): void {
  onAuthFailureCallback = callback;
}

/**
 * Single-flight refresh token handler.
 * If multiple requests receive a 401 concurrently, they share a single POST /auth/refresh call.
 */
export async function refreshSession(): Promise<string | null> {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        setAccessToken(null);
        if (onAuthFailureCallback) {
          onAuthFailureCallback();
        }
        return null;
      }

      const data = await response.json();
      const newToken = (data.access_token as string) || null;
      setAccessToken(newToken);
      return newToken;
    } catch {
      setAccessToken(null);
      if (onAuthFailureCallback) {
        onAuthFailureCallback();
      }
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Custom fetch implementation that attaches in-memory access token,
 * preserves incoming Request headers (like Content-Type: application/json),
 * ensures credentials: "include", and handles single-flight 401 auto-refresh and retry.
 */
export const authenticatedFetch: typeof fetch = async (input, init) => {
  let request: Request;
  let retryRequest: Request | null = null;

  if (input instanceof Request) {
    const headers = new Headers(input.headers);
    if (init?.headers) {
      const extra = new Headers(init.headers);
      extra.forEach((val, key) => headers.set(key, val));
    }
    if (inMemoryToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${inMemoryToken}`);
    }
    request = new Request(input, {
      ...init,
      credentials: 'include',
      headers,
    });
    try {
      retryRequest = request.clone();
    } catch {
      retryRequest = null;
    }
  } else {
    const headers = new Headers(init?.headers);
    if (inMemoryToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${inMemoryToken}`);
    }
    request = new Request(input, {
      ...init,
      credentials: 'include',
      headers,
    });
    try {
      retryRequest = request.clone();
    } catch {
      retryRequest = null;
    }
  }

  const isAuthEndpoint =
    request.url.includes('/auth/refresh') ||
    request.url.includes('/auth/login') ||
    request.url.includes('/auth/register');

  const response = await fetch(request);

  // If 401 and not an auth endpoint, attempt single-flight refresh and retry once
  if (response.status === 401 && !isAuthEndpoint) {
    const newToken = await refreshSession();
    if (newToken && retryRequest) {
      retryRequest.headers.set('Authorization', `Bearer ${newToken}`);
      return fetch(retryRequest);
    }
  }

  return response;
};

export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  fetch: authenticatedFetch,
});
