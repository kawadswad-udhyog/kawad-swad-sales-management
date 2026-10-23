/**
 * Central API Client for Kawad Swad Sales Management
 * Connects directly to the FastAPI backend on Render.
 */

// Default to the provided Render backend or user configured env var / window override
export const DEFAULT_API_BASE_URL =
  (typeof window !== 'undefined' && (window as unknown as { KAWAD_API_URL?: string }).KAWAD_API_URL) ||
  (typeof import.meta !== 'undefined' && (import.meta as unknown as { env?: { VITE_API_URL?: string } })?.env?.VITE_API_URL) ||
  '';

const STORAGE_API_KEY = 'ks_backend_api_url';
const STORAGE_TOKEN_KEY = 'ks_token';

export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const isProduction =
      window.location.hostname.includes('kawad-swad-sales-frontend.onrender.com') ||
      window.location.hostname.includes('onrender.com');
    const saved = localStorage.getItem(STORAGE_API_KEY)?.trim().replace(/\/$/, '');
    if (saved) {
      if (saved.includes('-dev.onrender.com') || saved.includes('kawad-swad-sales-dev')) {
        const replacement = isProduction ? 'https://kawad-swad-sales-backend.onrender.com' : '';
        if (replacement) {
          localStorage.setItem(STORAGE_API_KEY, replacement);
        } else {
          localStorage.removeItem(STORAGE_API_KEY);
        }
        return replacement;
      }
      return saved;
    }
    if (!DEFAULT_API_BASE_URL) {
      return isProduction ? 'https://kawad-swad-sales-backend.onrender.com' : '';
    }
  }
  const cleanDefault = (DEFAULT_API_BASE_URL || '').replace(/\/$/, '');
  if (cleanDefault.includes('-dev.onrender.com')) {
    return 'https://kawad-swad-sales-backend.onrender.com';
  }
  return cleanDefault;
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
  const timeoutMs = options.timeoutMs ?? 35000;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const targetUrl = baseUrl ? `${baseUrl}${path}` : path;

  try {
    let res: Response;
    try {
      res = await fetch(targetUrl, {
        ...options,
        headers,
        signal: controller.signal,
      });
    } catch (primaryErr: unknown) {
      // Dual-path resilience:
      // If external baseUrl failed, try local dev proxy (path)
      // If local proxy failed, try direct production Render backend fallback
      if (baseUrl && (baseUrl.startsWith('http://') || baseUrl.startsWith('https://'))) {
        try {
          res = await fetch(path, {
            ...options,
            headers,
            signal: controller.signal,
          });
        } catch {
          throw primaryErr;
        }
      } else if (!baseUrl || baseUrl === '') {
        try {
          const directBackendUrl = `https://kawad-swad-sales-backend.onrender.com${path}`;
          res = await fetch(directBackendUrl, {
            ...options,
            headers,
            signal: controller.signal,
          });
        } catch {
          throw primaryErr;
        }
      } else {
        throw primaryErr;
      }
    }

    clearTimeout(timeoutId);

    const isLoginEndpoint = path.includes('/login');
    if (res.status === 401 && !isLoginEndpoint) {
      setAuthToken('');
      window.dispatchEvent(new CustomEvent('ks_auth_expired'));
      throw new Error('Session expired or unauthorized. Please sign in again.');
    }

    const contentType = res.headers.get('content-type') || '';

    // Handle binary responses first
    if (contentType.includes('application/pdf') || contentType.includes('spreadsheetml')) {
      if (!res.ok) {
        throw new Error(`Server returned error status (${res.status} ${res.statusText || 'Error'})`);
      }
      return (await res.blob()) as unknown as T;
    }

    // Safely consume the response stream once as text to prevent stream exhaustion errors
    let rawText = '';
    try {
      rawText = await res.text();
    } catch {
      rawText = '';
    }

    // Safely attempt JSON parsing on non-empty body
    let parsedJson: any = null;
    const trimmed = rawText.trim();
    if (trimmed.length > 0) {
      try {
        parsedJson = JSON.parse(trimmed);
      } catch {
        parsedJson = null;
      }
    }

    if (!res.ok) {
      let errorMsg = '';
      if (parsedJson && typeof parsedJson === 'object') {
        errorMsg = parsedJson.detail || parsedJson.message || parsedJson.error || '';
      }

      if (!errorMsg && trimmed.length > 0) {
        if (trimmed.startsWith('<')) {
          if (res.status === 502) errorMsg = 'Backend service is starting up or temporarily unreachable (HTTP 502 Bad Gateway).';
          else if (res.status === 503) errorMsg = 'Backend service is temporarily unavailable (HTTP 503 Service Unavailable).';
          else if (res.status === 504) errorMsg = 'Gateway timed out waiting for backend (HTTP 504 Gateway Timeout).';
          else errorMsg = `Server returned an HTML error response (HTTP ${res.status}).`;
        } else {
          errorMsg = trimmed.slice(0, 160);
        }
      }

      if (!errorMsg) {
        if (res.status === 401) {
          errorMsg = isLoginEndpoint
            ? 'Invalid username or password. Please verify credentials.'
            : 'Session expired or unauthorized. Please sign in again.';
        } else if (res.status === 403) {
          errorMsg = 'Access forbidden. You do not have permission for this action.';
        } else if (res.status === 404) {
          errorMsg = `Requested endpoint was not found on the backend (${path}).`;
        } else if (res.status === 429) {
          errorMsg = 'Too many requests or temporary Google Sheets quota reached. Please wait 15 seconds and try again.';
        } else if (res.status >= 500) {
          errorMsg = `Backend server encountered an error (HTTP ${res.status}). Service may be spinning up.`;
        } else {
          errorMsg = `Server returned status ${res.status} (${res.statusText || 'Error'}).`;
        }
      }

      throw new Error(errorMsg);
    }

    // Return parsed JSON if valid
    if (parsedJson !== null) {
      return parsedJson as T;
    }

    // If body was empty but HTTP status was 2xx, return empty object
    if (trimmed.length === 0) {
      return ({} as unknown) as T;
    }

    // Otherwise return text payload
    return (rawText as unknown) as T;
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof Error) {
      if (err.name === 'AbortError') {
        throw new Error(
          `Request timed out after ${timeoutMs / 1000}s connecting to backend. Render free tier services may take 40-50s to wake up from cold standby.`
        );
      }
      if (
        err.message.includes('Failed to fetch') ||
        err.message.includes('NetworkError') ||
        err.message.includes('Load failed')
      ) {
        throw new Error(
          'Unable to reach backend API server. Please check your network connection or backend service status.'
        );
      }
      throw err;
    }
    throw new Error('An unexpected network or client error occurred.');
  }
}
