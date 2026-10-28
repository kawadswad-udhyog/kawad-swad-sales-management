/**
 * Central API Client for Kawad Swad Sales Management
 * Connects to FastAPI backend directly or via Vite dev server proxy.
 * Includes comprehensive debug logging for URL construction, CORS detection, and backend reachability.
 */

export const DEFAULT_API_BASE_URL =
  (typeof window !== 'undefined' && (window as unknown as { KAWAD_API_URL?: string }).KAWAD_API_URL) ||
  (typeof import.meta !== 'undefined' && (import.meta as unknown as { env?: { VITE_API_URL?: string } })?.env?.VITE_API_URL) ||
  '';

const STORAGE_API_KEY = 'ks_backend_api_url';
const STORAGE_TOKEN_KEY = 'ks_token';

export type ApiFailureCategory =
  | 'CORS_RESTRICTION'
  | 'URL_CONSTRUCTION_ERROR'
  | 'BACKEND_UNREACHABLE_OR_TIMEOUT'
  | 'BACKEND_5XX_GATEWAY'
  | 'AUTHENTICATION_REQUIRED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'RATE_LIMITED'
  | 'HTTP_ERROR'
  | 'NETWORK_ERROR';

export interface ApiLogEntry {
  id: string;
  timestamp: string;
  method: string;
  path: string;
  targetUrl: string;
  isProxied: boolean;
  status?: number;
  durationMs: number;
  ok: boolean;
  failureCategory?: ApiFailureCategory;
  errorMessage?: string;
  diagnostics?: string;
}

// In-memory ring buffer of recent API connection diagnostics
const _apiDebugLogs: ApiLogEntry[] = [];
const MAX_DEBUG_LOGS = 60;

function pushDebugLog(entry: ApiLogEntry) {
  _apiDebugLogs.unshift(entry);
  if (_apiDebugLogs.length > MAX_DEBUG_LOGS) {
    _apiDebugLogs.pop();
  }
}

export function getApiDebugLogs(): ApiLogEntry[] {
  return [..._apiDebugLogs];
}

export function clearApiDebugLogs(): void {
  _apiDebugLogs.length = 0;
}

/**
 * Determine the active API base URL.
 * When running in development, preview, or local environments (e.g. localhost, 127.0.0.1, or .run.app),
 * relative path routing is preferred by default so Vite's proxy handles forwarding, logging, and CORS bypass.
 */
export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const isProductionFrontend = hostname === 'kawad-swad-sales-frontend.onrender.com';

    // Production must use the Render static site's configured rewrites. Never let a
    // stale URL saved by Server Config redirect production traffic to an old/dev API.
    if (isProductionFrontend) return '';

    const saved = localStorage.getItem(STORAGE_API_KEY)?.trim().replace(/\/+$/, '');
    if (saved) {
      if (saved.includes('kawad-swad-sales-backend.onrender.com')) {
        localStorage.removeItem(STORAGE_API_KEY);
      } else {
        return saved;
      }
    }

    if (DEFAULT_API_BASE_URL) return DEFAULT_API_BASE_URL.replace(/\/+$/, '');
    return '';
  }

  return (DEFAULT_API_BASE_URL || '').replace(/\/+$/, '');
}

export function setApiBaseUrl(url: string): void {
  if (typeof window !== 'undefined') {
    const clean = url.trim().replace(/\/+$/, '');
    if (clean) {
      localStorage.setItem(STORAGE_API_KEY, clean);
    } else {
      localStorage.removeItem(STORAGE_API_KEY);
    }
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

/**
 * Safely constructs and validates target URL, eliminating double-slash anomalies.
 */
export function constructApiUrl(
  baseUrl: string,
  path: string
): { targetUrl: string; isProxied: boolean; error?: string } {
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  if (!baseUrl) {
    return { targetUrl: cleanPath, isProxied: true };
  }

  const cleanBase = baseUrl.trim().replace(/\/+$/, '');
  const combined = `${cleanBase}${cleanPath}`;

  try {
    // Validate URL syntax if absolute
    if (cleanBase.startsWith('http://') || cleanBase.startsWith('https://')) {
      new URL(combined);
      return { targetUrl: combined, isProxied: false };
    }
    return { targetUrl: combined, isProxied: true };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(`[ERP API Warning] Malformed base URL '${baseUrl}': ${msg}. Falling back to relative path '${cleanPath}'.`);
    return { targetUrl: cleanPath, isProxied: true, error: msg };
  }
}

export class ApiHttpError extends Error {
  status: number;
  category: ApiFailureCategory;
  targetUrl: string;
  isRenderNoServer: boolean;

  constructor(
    status: number,
    message: string,
    category: ApiFailureCategory,
    targetUrl: string,
    isRenderNoServer = false
  ) {
    super(message);
    this.name = 'ApiHttpError';
    this.status = status;
    this.category = category;
    this.targetUrl = targetUrl;
    this.isRenderNoServer = isRenderNoServer;
  }
}

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
  silent?: boolean;
}

export interface BackendHealthResponse {
  status: string;
  google_sheets_connected: boolean;
  persistent_writes_enabled: boolean;
  spreadsheet_id_configured?: boolean;
  service_account_configured?: boolean;
  last_connection_error?: string | null;
  allow_in_memory_fallback?: boolean;
  backend?: {
    status: string;
    service: string;
    version?: string;
  };
  google_sheets?: {
    status: string;
    connected: boolean;
    persistent_writes_enabled: boolean;
    message: string;
  };
  required_sheets?: {
    status: string;
    total_managed_tabs: number;
  };
}

/**
 * Robust API Request Executor with Dual-Path Resilience & Detailed Diagnostic Logging.
 */
export async function apiRequest<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
  const baseUrl = getApiBaseUrl();
  const token = getAuthToken();
  const timeoutMs = options.timeoutMs ?? 35000;
  const method = (options.method || 'GET').toUpperCase();

  const { targetUrl, isProxied, error: urlConstructionErr } = constructApiUrl(baseUrl, path);

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token && !token.startsWith('ks-local-jwt-')) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Grouped diagnostic log in browser console
  console.groupCollapsed(
    `[ERP API] ${method} ${targetUrl} [${isProxied ? 'Vite Proxy' : 'Direct URL'}]`
  );
  console.log('API Target:', {
    method,
    baseUrl: baseUrl || '(relative / Vite proxy)',
    path,
    targetUrl,
    isProxied,
    timeoutMs,
    hasAuthToken: Boolean(token),
  });

  if (urlConstructionErr) {
    console.warn('[ERP API] URL Construction Warning:', urlConstructionErr);
  }

  let res: Response | null = null;
  let didFallbackToProxy = false;
  let primaryFetchError: unknown = null;

  try {
    // 1. Primary Request Attempt
    try {
      res = await fetch(targetUrl, {
        ...options,
        headers,
        signal: controller.signal,
      });
    } catch (fetchErr: unknown) {
      primaryFetchError = fetchErr;

      // Classify whether primary failure was CORS or reachability
      const isCrossDomain =
        typeof window !== 'undefined' &&
        targetUrl.startsWith('http') &&
        !targetUrl.startsWith(window.location.origin);

      const isTypeError = fetchErr instanceof TypeError;
      const isNetworkError =
        fetchErr instanceof Error &&
        (fetchErr.message.includes('Failed to fetch') ||
          fetchErr.message.includes('NetworkError') ||
          fetchErr.message.includes('Load failed'));

      if (isCrossDomain && (isTypeError || isNetworkError)) {
        console.warn(
          `%c[ERP API: CORS Violation Detected]%c Direct cross-origin request to ${targetUrl} was blocked by the browser. Origin '${window.location.origin}' may not be in backend SALES_CORS_ORIGINS. Falling back to local Vite proxy.`,
          'color: #ef4444; font-weight: bold;',
          'color: inherit;'
        );
      } else {
        console.warn(
          `[ERP API: Primary Fetch Failed] ${fetchErr instanceof Error ? fetchErr.message : String(fetchErr)}. Attempting proxy fallback…`
        );
      }

      // 2. Dual-path fallback:
      // If external direct URL failed, fall back to local Vite proxy relative path
      // If local path failed and we have no baseUrl, attempt direct Render backend
      const cleanPath = path.startsWith('/') ? path : `/${path}`;
      if (!isProxied && (baseUrl.startsWith('http://') || baseUrl.startsWith('https://'))) {
        try {
          console.log(`[ERP API Recovery] Retrying via Vite proxy relative path: '${cleanPath}'`);
          res = await fetch(cleanPath, {
            ...options,
            headers,
            signal: controller.signal,
          });
          didFallbackToProxy = true;
          console.log(`%c[ERP API Recovery: Succeeded via Proxy]%c ${method} ${cleanPath} returned HTTP ${res.status}`, 'color: #10b981; font-weight: bold;', 'color: inherit;');
        } catch (fallbackErr: unknown) {
          console.error('[ERP API Recovery Failed] Proxy fallback also failed:', fallbackErr);
          throw primaryFetchError;
        }
      } else if (isProxied && (!baseUrl || baseUrl === '')) {
        // On production, relative URLs must go through the Render rewrite. Do not
        // silently jump to a hard-coded development service: that can authenticate
        // against the wrong database and split production data across environments.
        throw primaryFetchError;
      } else {
        throw primaryFetchError;
      }
    }

    clearTimeout(timeoutId);

    const endTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const durationMs = Math.round(endTime - startTime);

    const isLoginEndpoint = path.includes('/login');
    const isLogoutEndpoint = path.includes('/logout');
    if (res.status === 401 && !isLoginEndpoint) {
      const isLocalToken = Boolean(token && token.startsWith('ks-local-jwt-'));
      if (!isLocalToken) {
        setAuthToken('');
        if (!isLogoutEndpoint) {
          window.dispatchEvent(new CustomEvent('ks_auth_expired'));
        }
      }
      pushDebugLog({
        id: `log-${Date.now()}`,
        timestamp: new Date().toLocaleTimeString(),
        method,
        path,
        targetUrl: didFallbackToProxy ? path : targetUrl,
        isProxied: isProxied || didFallbackToProxy,
        status: 401,
        durationMs,
        ok: false,
        failureCategory: 'AUTHENTICATION_REQUIRED',
        errorMessage: 'Session expired or invalid credentials.',
      });
      console.warn(`[ERP API Notice: HTTP 401] Session expired or unauthorized for ${path}`);
      console.groupEnd();
      throw new ApiHttpError(
        401,
        'Session expired or unauthorized. Please sign in again.',
        'AUTHENTICATION_REQUIRED',
        targetUrl,
        false
      );
    }

    const contentType = res.headers.get('content-type') || '';

    // Handle binary responses (PDF invoice or Excel spreadsheets)
    if (contentType.includes('application/pdf') || contentType.includes('spreadsheetml')) {
      if (!res.ok) {
        throw new Error(`Server returned error status (${res.status} ${res.statusText || 'Error'})`);
      }
      console.log(`%c[ERP API Success: Binary Stream] HTTP ${res.status} in ${durationMs}ms`, 'color: #10b981;');
      console.groupEnd();
      return (await res.blob()) as unknown as T;
    }

    // Safely consume response stream as text once
    let rawText = '';
    try {
      rawText = await res.text();
    } catch {
      rawText = '';
    }

    // Safely parse JSON if non-empty
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
      const isRenderNoServer =
        res.status === 404 &&
        (res.headers.get('x-render-routing') === 'no-server' ||
          (trimmed.toLowerCase() === 'not found' && isProxied));

      let errorMsg = '';
      if (parsedJson && typeof parsedJson === 'object') {
        errorMsg = parsedJson.detail || parsedJson.message || parsedJson.error || '';
      }

      if (!errorMsg && trimmed.length > 0) {
        if (isRenderNoServer) {
          errorMsg = 'FastAPI backend service is sleeping or offline on Render (x-render-routing: no-server). Operating in Local Standby Mode.';
        } else if (trimmed.startsWith('<')) {
          if (res.status === 502) errorMsg = 'Backend service is starting up or temporarily unreachable (HTTP 502 Bad Gateway).';
          else if (res.status === 503) errorMsg = 'Backend service or Google Sheets storage is temporarily unavailable (HTTP 503 Service Unavailable).';
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
          errorMsg = isRenderNoServer
            ? 'FastAPI backend service is sleeping or offline on Render. Operating in Local Standby Mode.'
            : `Requested endpoint was not found on the backend (${path}).`;
        } else if (res.status === 429) {
          errorMsg = 'Too many requests or temporary Google Sheets quota reached. Please wait 15 seconds and try again.';
        } else if (res.status >= 500) {
          errorMsg = `Backend server encountered an error (HTTP ${res.status}). Service may be spinning up.`;
        } else {
          errorMsg = `Server returned status ${res.status} (${res.statusText || 'Error'}).`;
        }
      }

      let category: ApiFailureCategory = 'HTTP_ERROR';
      if (res.status === 401) category = 'AUTHENTICATION_REQUIRED';
      else if (res.status === 403) category = 'FORBIDDEN';
      else if (res.status === 404) category = 'NOT_FOUND';
      else if (res.status === 429) category = 'RATE_LIMITED';
      else if (res.status >= 500) category = 'BACKEND_5XX_GATEWAY';

      pushDebugLog({
        id: `log-${Date.now()}`,
        timestamp: new Date().toLocaleTimeString(),
        method,
        path,
        targetUrl: didFallbackToProxy ? path : targetUrl,
        isProxied: isProxied || didFallbackToProxy,
        status: res.status,
        durationMs,
        ok: false,
        failureCategory: category,
        errorMessage: errorMsg,
      });

      const isProbeOrSilent = Boolean(options.silent || path.includes('/health') || isRenderNoServer);
      if (isProbeOrSilent) {
        console.warn(`[ERP API Notice: HTTP ${res.status}] ${errorMsg}`);
      } else {
        console.error(`%c[ERP API Error: HTTP ${res.status}]%c ${errorMsg}`, 'color: #ef4444; font-weight: bold;', 'color: inherit;');
      }
      console.groupEnd();
      throw new ApiHttpError(res.status, errorMsg, category, targetUrl, isRenderNoServer);
    }

    // Success recording
    pushDebugLog({
      id: `log-${Date.now()}`,
      timestamp: new Date().toLocaleTimeString(),
      method,
      path,
      targetUrl: didFallbackToProxy ? path : targetUrl,
      isProxied: isProxied || didFallbackToProxy,
      status: res.status,
      durationMs,
      ok: true,
    });

    console.log(
      `%c[ERP API Success] ${method} ${targetUrl} -> HTTP ${res.status} (${durationMs}ms)%c`,
      'color: #10b981; font-weight: bold;',
      'color: inherit;',
      parsedJson || (trimmed ? rawText : '(empty body)')
    );
    console.groupEnd();

    if (parsedJson !== null) {
      return parsedJson as T;
    }
    if (trimmed.length === 0) {
      return ({} as unknown) as T;
    }
    return (rawText as unknown) as T;
  } catch (err: unknown) {
    clearTimeout(timeoutId);

    // If an ApiHttpError was already thrown above, do not log a second critical network error
    if (err instanceof ApiHttpError) {
      throw err;
    }

    const endTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const durationMs = Math.round(endTime - startTime);

    let category: ApiFailureCategory = 'NETWORK_ERROR';
    let diagnosticDetails = '';

    if (err instanceof Error) {
      if (err.name === 'AbortError') {
        category = 'BACKEND_UNREACHABLE_OR_TIMEOUT';
        diagnosticDetails = `Request timed out after ${timeoutMs / 1000}s. The Render free-tier web service is likely sleeping and requires 40-50s to cold start.`;
      } else if (
        err.message.includes('Failed to fetch') ||
        err.message.includes('NetworkError') ||
        err.message.includes('Load failed')
      ) {
        const isCrossDomain =
          typeof window !== 'undefined' &&
          targetUrl.startsWith('http') &&
          !targetUrl.startsWith(window.location.origin);

        if (isCrossDomain) {
          category = 'CORS_RESTRICTION';
          diagnosticDetails = `Cross-origin request to ${targetUrl} was blocked by the browser. Current origin '${window.location.origin}' is not permitted by backend CORS headers. Use the Vite proxy relative path instead.`;
        } else {
          category = 'BACKEND_UNREACHABLE_OR_TIMEOUT';
          diagnosticDetails = `Unable to connect to backend at ${targetUrl}. Service may be restarting, sleeping, or port 3000 proxy is waiting for upstream.`;
        }
      } else {
        diagnosticDetails = err.message;
      }
    }

    pushDebugLog({
      id: `log-${Date.now()}`,
      timestamp: new Date().toLocaleTimeString(),
      method,
      path,
      targetUrl,
      isProxied,
      durationMs,
      ok: false,
      failureCategory: category,
      errorMessage: err instanceof Error ? err.message : String(err),
      diagnostics: diagnosticDetails,
    });

    const isProbeOrSilent = Boolean(
      options.silent || path.includes('/health') || category === 'BACKEND_UNREACHABLE_OR_TIMEOUT'
    );
    if (isProbeOrSilent) {
      console.warn(`[ERP API Network Notice: ${category}] ${diagnosticDetails || (err instanceof Error ? err.message : String(err))}`);
    } else {
      console.error(
        `%c[ERP API Critical Failure: ${category}]%c ${diagnosticDetails || (err instanceof Error ? err.message : String(err))}`,
        'color: #ef4444; font-weight: bold;',
        'color: inherit;',
        { targetUrl, isProxied, durationMs, error: err }
      );
    }
    console.groupEnd();

    if (err instanceof Error) {
      if (err.name === 'AbortError') {
        throw new Error(
          `Request timed out after ${timeoutMs / 1000}s connecting to backend. Render free tier services may take 40-50s to wake up from cold standby.`
        );
      }
      if (category === 'CORS_RESTRICTION') {
        throw new Error(
          `CORS Error: Backend server did not allow connection from ${typeof window !== 'undefined' ? window.location.origin : 'this origin'}. Using the Vite proxy will bypass this issue.`
        );
      }
      if (category === 'BACKEND_UNREACHABLE_OR_TIMEOUT') {
        throw new Error(
          'Unable to reach backend API server. Please check your network connection or verify that the Render backend service is running.'
        );
      }
      throw err;
    }
    throw new Error('An unexpected network or client error occurred.');
  }
}

/**
 * Resilient, probe-safe health check that never throws unhandled errors to the UI or console.
 */
export async function fetchBackendHealth(): Promise<BackendHealthResponse> {
  try {
    const res = await apiRequest<BackendHealthResponse>('/api/health', {
      timeoutMs: 8000,
      silent: true,
    });
    return res;
  } catch (err: unknown) {
    if (err instanceof ApiHttpError && err.status === 404 && !err.isRenderNoServer) {
      try {
        const alt = await apiRequest<BackendHealthResponse>('/health', {
          timeoutMs: 8000,
          silent: true,
        });
        return alt;
      } catch {
        // Fall through to standby state below
      }
    }

    const isNoServer = err instanceof ApiHttpError && err.isRenderNoServer;
    const msg = isNoServer
      ? 'Render backend is in standby / offline (x-render-routing: no-server). Local Standby Mode active.'
      : err instanceof Error
      ? err.message
      : 'Backend unreachable. Operating in Local Standby Mode.';

    return {
      status: 'standby',
      google_sheets_connected: false,
      persistent_writes_enabled: false,
      spreadsheet_id_configured: false,
      service_account_configured: false,
      last_connection_error: msg,
      allow_in_memory_fallback: true,
      backend: {
        status: 'STANDBY',
        service: 'kawad-swad-sales-dev',
        version: '1.0.0',
      },
      google_sheets: {
        status: 'STANDBY',
        connected: false,
        persistent_writes_enabled: false,
        message: 'Standby Mode active. Connect Google Sheets in settings or Render dashboard to enable live persistence.',
      },
      required_sheets: {
        status: 'STANDBY',
        total_managed_tabs: 28,
      },
    };
  }
}

export interface RawMaterialSummary {
  material_id: string;
  material_name: string;
  category: string;
  unit: string;
  baseline_stock: number;
  total_received: number;
  total_consumed: number;
  total_adjusted: number;
  available_stock: number;
  latest_landed_rate: number;
}

export interface RawMaterialReceiveInput {
  material_id: string;
  material_name?: string;
  quantity: number;
  unit: string;
  purchase_rate: number;
  receipt_date?: string;
  supplier_name: string;
  invoice_reference: string;
  line_number?: number;
  freight_amount?: number;
  other_expenses?: number;
  gst_amount?: number;
  gst_treatment?: 'RECOVERABLE_ITC' | 'CAPITALIZED_TO_COST' | 'EXEMPT_NIL_RATED';
  notes?: string;
}

export interface RawMaterialReceiveResult {
  status: string;
  message: string;
  transaction_id: string;
  material_id: string;
  material_name: string;
  quantity: number;
  unit: string;
  landed_rate_per_unit: number;
  base_value: number;
  freight_amount: number;
  other_expenses: number;
  gst_amount: number;
  gst_treatment: string;
  total_landed_cost: number;
  new_available_stock: number;
  is_replay: boolean;
}

export async function getRawMaterials(): Promise<RawMaterialSummary[]> {
  return apiRequest<RawMaterialSummary[]>('/api/production/raw-materials');
}

export async function receiveRawMaterial(data: RawMaterialReceiveInput): Promise<RawMaterialReceiveResult> {
  return apiRequest<RawMaterialReceiveResult>('/api/production/raw-materials/receive', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}
