/**
 * Central API Client for Kawad Swad Sales Management
 * Connects directly to the FastAPI backend on Render.
 */

// Default to the provided Render backend or user configured env var / window override
export const DEFAULT_API_BASE_URL =
  (typeof window !== 'undefined' && (window as unknown as { KAWAD_API_URL?: string }).KAWAD_API_URL) ||
  (typeof import.meta !== 'undefined' && (import.meta as unknown as { env?: { VITE_API_URL?: string } })?.env?.VITE_API_URL) ||
  'https://kawad-swad-sales-dev.onrender.com';

const STORAGE_API_KEY = 'ks_backend_api_url';
const STORAGE_TOKEN_KEY = 'ks_token';

export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem(STORAGE_API_KEY);
    if (saved) return saved.replace(/\/$/, '');
  }
  return DEFAULT_API_BASE_URL.replace(/\/$/, '');
}

export function setApiBaseUrl(url: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_API_KEY, url.trim().replace(/\/$/, ''));
  }
}

export function getAuthToken(): string {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(STORAGE_TOKEN_KEY) || '';
  }
  return '';
}

export function setAuthToken(token: string): void {
  if (typeof window !== 'undefined') {
    if (token) {
      localStorage.setItem(STORAGE_TOKEN_KEY, token);
    } else {
      localStorage.removeItem(STORAGE_TOKEN_KEY);
    }
  }
}

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
}

export async function apiRequest<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const token = getAuthToken();
  const timeoutMs = options.timeoutMs ?? 25000;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (res.status === 401) {
      setAuthToken('');
      window.dispatchEvent(new CustomEvent('ks_auth_expired'));
      throw new Error('Session expired or unauthorized. Please sign in again.');
    }

    const contentType = res.headers.get('content-type') || '';

    if (!res.ok) {
      let errorMsg = `Server error (${res.status})`;
      try {
        const errJson = await res.json();
        errorMsg = errJson.detail || errJson.message || errorMsg;
      } catch {
        const text = await res.text();
        if (text) errorMsg = text.slice(0, 150);
      }
      throw new Error(errorMsg);
    }

    if (contentType.includes('application/pdf') || contentType.includes('spreadsheetml')) {
      return (await res.blob()) as unknown as T;
    }

    return (await res.json()) as T;
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof Error) {
      if (err.name === 'AbortError') {
        throw new Error(`Request timed out after ${timeoutMs / 1000}s connecting to ${baseUrl}. If using Render free tier, the service may be spinning up.`);
      }
      if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
        throw new Error(`Unable to reach backend at ${baseUrl}. Please check network connection or verify CORS configuration.`);
      }
      throw err;
    }
    throw new Error('An unknown network error occurred.');
  }
}
