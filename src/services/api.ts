/**
 * Central API Client for Kawad Swad Sales Management
 * Connects to FastAPI backend directly or via Vite dev server proxy.
 * Includes comprehensive debug logging for URL construction, CORS detection, and backend reachability.
 */

import type {
  Supplier,
  PurchaseOrder,
  GoodsReceipt,
  SupplierBill,
  SupplierPayment,
  SupplierReturn,
  QualityCheck,
  ProductLot,
  LotMovement,
  CustomerReturn,
  ComplaintRecall,
  MillingBatch,
  DebtorItem,
  CreditorItem,
  CashBankReport,
  GstSummaryReport,
  AccountingPeriod,
  VanLoadingPass,
  VanLoadingPassCreate,
  ErpCapabilitiesPayload,
  PendingCaPolicy,
  ReportTabPayload,
  PaginatedV2Response,
  SchemaRegistryPayload,
  V2ErrorDetail,
  WorkflowState,
} from '../types';

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

function isDisallowedBackendOverride(url: string): boolean {
  const lower = url.toLowerCase();
  return (
    lower.includes('kawad-swad-sales-backend.onrender.com') ||
    lower.includes('example.com') ||
    lower.includes('your-backend') ||
    lower.includes('replace-with-prod')
  );
}

/**
 * Determine the active API base URL.
 * Deployed origins (https://kawad-swad-sales-frontend.onrender.com) never honor stale localStorage overrides;
 * they use build-time VITE_API_URL or same-origin relative routing (/api/* -> https://kawad-swad-sales-dev.onrender.com).
 */
export function getApiBaseUrl(): string {
  const rawDefault = (DEFAULT_API_BASE_URL || '').trim().replace(/\/+$/, '');
  const cleanDefault = rawDefault && !isDisallowedBackendOverride(rawDefault) ? rawDefault : '';

  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    const isLocalHost =
      hostname === 'localhost' ||
      hostname === '127.0.0.1' ||
      hostname === '::1' ||
      hostname.endsWith('.local');

    const saved = localStorage.getItem(STORAGE_API_KEY)?.trim().replace(/\/+$/, '');
    if (saved && isDisallowedBackendOverride(saved)) {
      localStorage.removeItem(STORAGE_API_KEY);
    }

    // Never allow stale localStorage overrides on deployed/production frontends.
    if (!isLocalHost) {
      if (saved) {
        localStorage.removeItem(STORAGE_API_KEY);
      }
      return cleanDefault;
    }

    if (saved && !isDisallowedBackendOverride(saved)) {
      return saved;
    }

    return cleanDefault;
  }

  return cleanDefault;
}

export function setApiBaseUrl(url: string): void {
  if (typeof window !== 'undefined') {
    const clean = url.trim().replace(/\/+$/, '');
    if (clean && !isDisallowedBackendOverride(clean)) {
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

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
  silent?: boolean;
  idempotencyKey?: string;
}

function extractBodyIdempotencyKey(body: BodyInit | null | undefined): string {
  if (typeof body !== 'string') return '';
  const trimmed = body.trim();
  if (!trimmed.startsWith('{')) return '';
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const candidate = parsed.nonce || parsed.idempotency_key;
      return typeof candidate === 'string' ? candidate.trim() : '';
    }
  } catch {
    // Ignore non-JSON body payloads
  }
  return '';
}

function resolveRequestIdempotencyKey(
  path: string,
  method: string,
  options: ApiRequestOptions,
  headers: Record<string, string>
): string {
  const upperMethod = (method || 'GET').toUpperCase();
  const explicit = (
    options.idempotencyKey ||
    headers['X-KS-Idempotency-Key'] ||
    headers['x-ks-idempotency-key'] ||
    headers['X-Idempotency-Key'] ||
    headers['x-idempotency-key'] ||
    extractBodyIdempotencyKey(options.body) ||
    ''
  ).trim();
  if (explicit) return explicit;
  if (
    upperMethod !== 'GET' &&
    upperMethod !== 'HEAD' &&
    upperMethod !== 'OPTIONS' &&
    !path.includes('/auth/') &&
    !path.includes('/health')
  ) {
    return createSubmissionNonce('REQ');
  }
  return '';
}

/**
 * Shared fetch helper ensuring all API calls respect the configured API Base URL
 * and inject standard authentication and idempotency headers.
 */
export async function apiFetch(path: string, options: ApiRequestOptions = {}): Promise<Response> {
  const baseUrl = getApiBaseUrl();
  const token = getAuthToken();
  const { targetUrl } = constructApiUrl(baseUrl, path);
  const method = (options.method || 'GET').toUpperCase();
  const timeoutMs = options.timeoutMs ?? 35000;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token && !token.startsWith('ks-local-jwt-') && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const resolvedIdempotencyKey = resolveRequestIdempotencyKey(path, method, options, headers);
  if (resolvedIdempotencyKey && !headers['X-KS-Idempotency-Key']) {
    headers['X-KS-Idempotency-Key'] = resolvedIdempotencyKey;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(targetUrl, {
      ...options,
      headers,
      signal: options.signal ?? controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiOutcomeUnknownError(
        UNKNOWN_OUTCOME_STANDARD_MSG,
        resolvedIdempotencyKey || undefined
      );
    }
    throw err;
  }
  clearTimeout(timeoutId);

  if (res.status === 504) {
    let msg = UNKNOWN_OUTCOME_STANDARD_MSG;
    let corrId: string | undefined;
    let respNonce: string | undefined;
    try {
      const payload = await res.clone().json();
      const detail = payload?.detail;
      if (detail && typeof detail === 'object') {
        if (typeof detail.message === 'string' && detail.message.trim()) {
          msg = `Outcome unknown / checking transaction status — ${detail.message}`;
        }
        if (typeof detail.correlation_id === 'string') corrId = detail.correlation_id;
        if (typeof detail.nonce === 'string') respNonce = detail.nonce;
      } else if (typeof payload?.message === 'string' && payload.message.trim()) {
        msg = `Outcome unknown / checking transaction status — ${payload.message}`;
      }
    } catch {
      // Ignore parse failure on 504
    }
    throw new ApiOutcomeUnknownError(msg, respNonce || resolvedIdempotencyKey || undefined, corrId);
  }

  return res;
}

export type TransactionLifecycleState =
  | 'INITIATED'
  | 'VALIDATING'
  | 'PENDING'
  | 'EXECUTING'
  | 'COMMITTED'
  | 'FAILED'
  | 'UNKNOWN'
  | 'RECOVERY_REQUIRED'
  | 'RECONCILED';

export type TransactionFailureCategory =
  | 'VALIDATION_ERROR'
  | 'AUTHORIZATION_ERROR'
  | 'DUPLICATE_REQUEST'
  | 'IDEMPOTENCY_CONFLICT'
  | 'DEPENDENCY_UNAVAILABLE'
  | 'WRITE_REJECTED'
  | 'WRITE_FAILED_CONFIRMED'
  | 'WRITE_OUTCOME_UNKNOWN'
  | 'VERIFICATION_FAILED'
  | 'RECOVERY_REQUIRED'
  | 'INTERNAL_ERROR';

export class ApiHttpError extends Error {
  status: number;
  category: ApiFailureCategory;
  targetUrl: string;
  isRenderNoServer: boolean;
  errorCode?: string;
  correlationId?: string;
  retryable?: boolean;
  workflowStatus?: WorkflowState;
  transactionId?: string;
  transactionState?: TransactionLifecycleState;
  failureCategory?: TransactionFailureCategory;
  nonce?: string;
  recoveryDecision?: string;

  constructor(
    status: number,
    message: string,
    category: ApiFailureCategory,
    targetUrl: string,
    isRenderNoServer = false,
    extra?: {
      errorCode?: string;
      correlationId?: string;
      retryable?: boolean;
      workflowStatus?: WorkflowState;
      transactionId?: string;
      transactionState?: TransactionLifecycleState;
      failureCategory?: TransactionFailureCategory;
      nonce?: string;
      recoveryDecision?: string;
    }
  ) {
    super(message);
    this.name = 'ApiHttpError';
    this.status = status;
    this.category = category;
    this.targetUrl = targetUrl;
    this.isRenderNoServer = isRenderNoServer;
    this.errorCode = extra?.errorCode;
    this.correlationId = extra?.correlationId;
    this.retryable = extra?.retryable;
    this.workflowStatus = extra?.workflowStatus;
    this.transactionId = extra?.transactionId;
    this.transactionState = extra?.transactionState;
    this.failureCategory = extra?.failureCategory;
    this.nonce = extra?.nonce;
    this.recoveryDecision = extra?.recoveryDecision;
  }
}

export const BLOCKED_OWNER_SETUP_ERROR_CODES = new Set<string>([
  'BLOCKED_PENDING_OWNER_SETUP',
  'CORE_SCHEMA_CONFLICT_UNRECONCILED',
  'PENDING_OWNER_MAPPING',
  'CONFLICT_RECONCILIATION_REQUIRED',
  'APPS_SCRIPT_BRIDGE_UNCONFIGURED',
]);

export interface NormalizedApiErrorPayload {
  errorMsg: string;
  errorCode?: string;
  correlationId?: string;
  retryable?: boolean;
  workflowStatus?: WorkflowState;
  transactionId?: string;
  transactionState?: TransactionLifecycleState;
  failureCategory?: TransactionFailureCategory;
  nonce?: string;
  recoveryDecision?: string;
}

export function normalizeApiErrorPayload(
  parsedJson: Record<string, any> | null | undefined,
  httpStatus: number
): NormalizedApiErrorPayload {
  if (!parsedJson || typeof parsedJson !== 'object') {
    return {
      errorMsg: '',
      retryable: httpStatus === 503 ? false : undefined,
    };
  }
  const detailObj =
    parsedJson.detail && typeof parsedJson.detail === 'object'
      ? (parsedJson.detail as Record<string, any>)
      : null;
  const errorCode = detailObj?.error_code || parsedJson.error_code;
  const correlationId = detailObj?.correlation_id || parsedJson.correlation_id;
  const transactionId = detailObj?.transaction_id || parsedJson.transaction_id;
  const rawTxState = String(detailObj?.transaction_state || parsedJson.transaction_state || '')
    .trim()
    .toUpperCase();
  const rawFailCat = String(detailObj?.failure_category || parsedJson.failure_category || '')
    .trim()
    .toUpperCase();
  const nonce = detailObj?.nonce || detailObj?.idempotency_key || parsedJson.nonce;
  const recoveryDecision = detailObj?.recovery_decision || parsedJson.recovery_decision;
  const rawRetryable = detailObj?.retryable ?? parsedJson.retryable;
  const backendStatus = String(detailObj?.status || parsedJson.status || '')
    .trim()
    .toUpperCase();

  let workflowStatus: WorkflowState | undefined = detailObj?.workflow_status;
  if (
    !workflowStatus &&
    (backendStatus === 'BLOCKED_PENDING_OWNER_SETUP' ||
      (errorCode && BLOCKED_OWNER_SETUP_ERROR_CODES.has(String(errorCode).trim().toUpperCase())))
  ) {
    workflowStatus = 'BLOCKED_PENDING_OWNER_SETUP';
  } else if (!workflowStatus && backendStatus === 'PENDING_UNKNOWN') {
    workflowStatus = 'PENDING_UNKNOWN';
  }

  const isRecoveryReq =
    backendStatus === 'RECOVERY_REQUIRED' ||
    rawTxState === 'RECOVERY_REQUIRED' ||
    rawFailCat === 'RECOVERY_REQUIRED';

  const transactionState = (rawTxState ||
    (isRecoveryReq
      ? 'RECOVERY_REQUIRED'
      : backendStatus === 'PENDING_UNKNOWN' || httpStatus === 504
      ? 'UNKNOWN'
      : undefined)) as TransactionLifecycleState | undefined;

  const failureCategory = (rawFailCat ||
    (isRecoveryReq ? 'RECOVERY_REQUIRED' : undefined)) as TransactionFailureCategory | undefined;

  const retryable =
    workflowStatus === 'BLOCKED_PENDING_OWNER_SETUP' || isRecoveryReq
      ? false
      : typeof rawRetryable === 'boolean'
      ? rawRetryable
      : undefined;

  const rawDetail =
    detailObj?.detail ||
    detailObj?.message ||
    (typeof parsedJson.detail === 'string' ? parsedJson.detail : '') ||
    parsedJson.message ||
    parsedJson.error ||
    '';

  return {
    errorMsg: String(rawDetail),
    errorCode: errorCode ? String(errorCode) : undefined,
    correlationId: correlationId ? String(correlationId) : undefined,
    retryable,
    workflowStatus,
    transactionId: transactionId ? String(transactionId) : undefined,
    transactionState,
    failureCategory,
    nonce: nonce ? String(nonce) : undefined,
    recoveryDecision: recoveryDecision ? String(recoveryDecision) : undefined,
  };
}

export function isRecoveryRequiredError(err: unknown): boolean {
  if (err instanceof ApiHttpError) {
    return (
      err.transactionState === 'RECOVERY_REQUIRED' ||
      err.failureCategory === 'RECOVERY_REQUIRED' ||
      Boolean(err.errorCode && err.errorCode.toUpperCase().includes('RECOVERY_REQUIRED'))
    );
  }
  return false;
}

export function isBlockedOwnerSetupError(err: unknown): boolean {
  if (err instanceof ApiHttpError) {
    if (err.workflowStatus === 'BLOCKED_PENDING_OWNER_SETUP') return true;
    if (err.errorCode && BLOCKED_OWNER_SETUP_ERROR_CODES.has(err.errorCode.toUpperCase())) {
      return true;
    }
  }
  return false;
}

export type SchemaBadgeTone = 'verified' | 'blocked' | 'pending' | 'unknown';

export interface SchemaStatusBadgeInfo {
  tone: SchemaBadgeTone;
  label: string;
  writableImplied: false;
  className: string;
}

export function classifySchemaStatusBadge(rawStatus?: string | null): SchemaStatusBadgeInfo {
  const status = String(rawStatus || '').trim().toUpperCase();
  if (status === 'VERIFIED_CORE' || status === 'RECONCILED_OWNER_APPROVED' || status === 'COMPLETE_VERIFIED') {
    return {
      tone: 'verified',
      label: status,
      writableImplied: false,
      className: 'bg-emerald-100 text-emerald-800',
    };
  }
  if (
    status.includes('CONFLICT') ||
    status.includes('BLOCKED') ||
    status === 'CORE_SCHEMA_CONFLICT_UNRECONCILED'
  ) {
    return {
      tone: 'blocked',
      label: status,
      writableImplied: false,
      className: 'bg-red-100 text-red-800',
    };
  }
  if (status.includes('PENDING') || status.includes('INCOMPLETE')) {
    return {
      tone: 'pending',
      label: status,
      writableImplied: false,
      className: 'bg-amber-100 text-amber-800',
    };
  }
  return {
    tone: 'unknown',
    label: status || 'UNKNOWN_STATUS',
    writableImplied: false,
    className: 'bg-slate-200 text-slate-800',
  };
}

export const UNKNOWN_OUTCOME_STANDARD_MSG =
  'Outcome unknown / checking transaction status — do not submit a new transaction. Form inputs are NOT SAVED and your retry nonce is preserved.';

export interface UnknownOutcomeState {
  nonce: string;
  correlationId?: string;
  transactionId?: string;
  transactionState?: TransactionLifecycleState;
  message: string;
  actionLabel?: string;
  recoveryRequired?: boolean;
}

export interface TransactionStatusResponse {
  status:
    | 'CONFIRMED_RECORDED'
    | 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'
    | 'UNKNOWN_STORAGE_UNAVAILABLE'
    | 'RECOVERY_REQUIRED'
    | 'RECONCILED'
    | 'IN_PROGRESS';
  transaction_id?: string | null;
  transaction_state?: TransactionLifecycleState | null;
  failure_category?: TransactionFailureCategory | null;
  nonce: string;
  correlation_id?: string | null;
  allocated_id?: string | null;
  tab_name?: string | null;
  recorded_at?: string | null;
  audit_entry?: {
    audit_id?: string;
    event_datetime?: string;
    action?: string;
    entity_type?: string;
    entity_id?: string;
  } | null;
  safe_to_retry_same_nonce: boolean;
  recovery_decision?: string | null;
  checked_at: string;
  message: string;
}

export class ApiOutcomeUnknownError extends Error {
  nonce?: string;
  correlationId?: string;
  transactionId?: string;

  constructor(message: string, nonce?: string, correlationId?: string, transactionId?: string) {
    super(message);
    this.name = 'ApiOutcomeUnknownError';
    this.nonce = nonce;
    this.correlationId = correlationId;
    this.transactionId = transactionId;
  }
}

export function createSubmissionNonce(prefix = 'NONCE'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
}

export function isUnknownOutcomeError(err: unknown): boolean {
  if (err instanceof ApiOutcomeUnknownError) return true;
  if (isRecoveryRequiredError(err)) return true;
  if (
    err instanceof ApiHttpError &&
    (err.status === 504 ||
      err.workflowStatus === 'PENDING_UNKNOWN' ||
      err.errorCode === 'PENDING_UNKNOWN' ||
      err.transactionState === 'UNKNOWN')
  ) {
    return true;
  }
  if (err instanceof Error) {
    const m = err.message.toLowerCase();
    return (
      m.includes('outcome unknown') ||
      m.includes('status not confirmed') ||
      m.includes('timed out') ||
      m.includes('timeout')
    );
  }
  return false;
}

export function extractUnknownOutcomeInfo(
  err: unknown,
  fallbackNonce?: string,
  actionLabel?: string
): UnknownOutcomeState | null {
  if (!isUnknownOutcomeError(err)) return null;
  const recoveryRequired = isRecoveryRequiredError(err);
  const nonce =
    (err instanceof ApiOutcomeUnknownError && err.nonce) ||
    (err instanceof ApiHttpError && err.nonce) ||
    fallbackNonce ||
    '';
  const correlationId =
    (err instanceof ApiOutcomeUnknownError && err.correlationId) ||
    (err instanceof ApiHttpError && err.correlationId) ||
    undefined;
  const transactionId =
    (err instanceof ApiOutcomeUnknownError && err.transactionId) ||
    (err instanceof ApiHttpError && err.transactionId) ||
    undefined;
  const rawMsg = err instanceof Error && err.message ? err.message : UNKNOWN_OUTCOME_STANDARD_MSG;
  const message =
    recoveryRequired || rawMsg.toLowerCase().includes('outcome unknown')
      ? rawMsg
      : UNKNOWN_OUTCOME_STANDARD_MSG;
  return {
    nonce,
    correlationId,
    transactionId,
    transactionState: recoveryRequired ? 'RECOVERY_REQUIRED' : 'UNKNOWN',
    recoveryRequired,
    message,
    actionLabel,
  };
}

export interface BackendHealthResponse {
  status: string;
  google_sheets_connected: boolean;
  persistent_writes_enabled: boolean;
  apps_script_bridge_configured?: boolean;
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

// Synchronous in-flight mutation deduplication guard (blocks millisecond double-clicks
// across all views before React state re-renders, without affecting read-only GET queries).
const inflightMutationKeys = new Set<string>();

export function getInflightMutationCount(): number {
  return inflightMutationKeys.size;
}

/**
 * Robust API Request Executor with Read-Only Dual-Path Resilience, Synchronous Mutation
 * Deduplication, and Fail-Closed Transaction Safety.
 */
export async function apiRequest<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const startTime = typeof performance !== 'undefined' ? performance.now() : Date.now();
  const baseUrl = getApiBaseUrl();
  const token = getAuthToken();
  const timeoutMs = options.timeoutMs ?? 35000;
  const method = (options.method || 'GET').toUpperCase();
  const isReadOnlyMethod = method === 'GET' || method === 'HEAD' || method === 'OPTIONS';
  const isAuthOrHealth = path.includes('/auth/') || path.includes('/health');

  const { targetUrl, isProxied, error: urlConstructionErr } = constructApiUrl(baseUrl, path);

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token && !token.startsWith('ks-local-jwt-')) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const resolvedIdempotencyKey = resolveRequestIdempotencyKey(path, method, options, headers);
  if (resolvedIdempotencyKey && !headers['X-KS-Idempotency-Key']) {
    headers['X-KS-Idempotency-Key'] = resolvedIdempotencyKey;
  }

  const flightKey =
    !isReadOnlyMethod && !isAuthOrHealth && resolvedIdempotencyKey
      ? `${method}:${path}:${resolvedIdempotencyKey}`
      : '';
  if (flightKey) {
    if (inflightMutationKeys.has(flightKey)) {
      throw new ApiHttpError(
        409,
        'This transaction is already submitting. Duplicate click blocked to prevent double submission.',
        'HTTP_ERROR',
        targetUrl,
        false,
        {
          errorCode: 'CONCURRENT_DUPLICATE_REQUEST',
          retryable: true,
          transactionState: 'PENDING',
          failureCategory: 'DUPLICATE_REQUEST',
          nonce: resolvedIdempotencyKey,
        }
      );
    }
    inflightMutationKeys.add(flightKey);
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
          `%c[ERP API: CORS Violation Detected]%c Direct cross-origin request to ${targetUrl} was blocked by the browser. Origin '${window.location.origin}' may not be in backend SALES_CORS_ORIGINS.`,
          'color: #ef4444; font-weight: bold;',
          'color: inherit;'
        );
      } else {
        console.warn(
          `[ERP API: Primary Fetch Failed] ${fetchErr instanceof Error ? fetchErr.message : String(fetchErr)}.`
        );
      }

      // 2. Dual-path fallback:
      // STRICT TRANSACTION SAFETY RULE (Mission 51B-1):
      // Automatic fallback retry is ONLY allowed for idempotent read-only methods (GET/HEAD/OPTIONS).
      // Mutating requests (POST/PUT/PATCH/DELETE) MUST NEVER auto-retry blindly on network errors
      // because the primary request may already have reached the backend and committed.
      const cleanPath = path.startsWith('/') ? path : `/${path}`;
      if (isReadOnlyMethod && !isProxied && (baseUrl.startsWith('http://') || baseUrl.startsWith('https://'))) {
        try {
          console.log(`[ERP API Recovery] Retrying read-only request via Vite proxy relative path: '${cleanPath}'`);
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
      let errorCode: string | undefined;
      let correlationId: string | undefined;
      let retryable: boolean | undefined;
      let workflowStatus: WorkflowState | undefined;
      let transactionId: string | undefined;
      let transactionState: TransactionLifecycleState | undefined;
      let failureCategory: TransactionFailureCategory | undefined;
      let responseNonce: string | undefined;
      let recoveryDecision: string | undefined;
      if (parsedJson && typeof parsedJson === 'object') {
        const normalized = normalizeApiErrorPayload(parsedJson, res.status);
        errorCode = normalized.errorCode;
        correlationId = normalized.correlationId;
        retryable = normalized.retryable;
        workflowStatus = normalized.workflowStatus;
        transactionId = normalized.transactionId;
        transactionState = normalized.transactionState;
        failureCategory = normalized.failureCategory;
        responseNonce = normalized.nonce;
        recoveryDecision = normalized.recoveryDecision;
        errorMsg = normalized.errorMsg;
      }

      if (!errorMsg && trimmed.length > 0) {
        if (isRenderNoServer) {
          errorMsg = 'Backend service is currently unreachable on Render (x-render-routing: no-server). All governed writes are locked.';
        } else if (trimmed.startsWith('<')) {
          if (res.status === 502) errorMsg = 'Backend service is starting up or temporarily unreachable (HTTP 502 Bad Gateway).';
          else if (res.status === 503) errorMsg = 'Backend service or Google Sheets storage is temporarily unavailable (HTTP 503 Service Unavailable).';
          else if (res.status === 504) errorMsg = 'Status not confirmed; do not submit a new transaction. Gateway timed out waiting for backend (HTTP 504).';
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
            ? 'Backend service is currently unreachable on Render. All governed writes are locked.'
            : `Requested endpoint was not found on the backend (${path}).`;
        } else if (res.status === 429) {
          errorMsg = 'Too many requests or temporary Google Sheets quota reached. Please wait 15 seconds and try again.';
        } else if (res.status === 503) {
          errorMsg = 'Service unavailable or write blocked pending owner setup (HTTP 503). Record NOT SAVED.';
        } else if (res.status === 504) {
          errorMsg = 'Status not confirmed; do not submit a new transaction.';
        } else if (res.status >= 500) {
          errorMsg = `Backend server encountered an error (HTTP ${res.status}).`;
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
      const effectiveNonce = responseNonce || resolvedIdempotencyKey || undefined;
      if (res.status === 504 && !isReadOnlyMethod) {
        throw new ApiOutcomeUnknownError(
          UNKNOWN_OUTCOME_STANDARD_MSG,
          effectiveNonce,
          correlationId,
          transactionId
        );
      }
      throw new ApiHttpError(res.status, errorMsg, category, targetUrl, isRenderNoServer, {
        errorCode,
        correlationId,
        retryable,
        workflowStatus,
        transactionId,
        transactionState,
        failureCategory,
        nonce: effectiveNonce,
        recoveryDecision,
      });
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

    // If an ApiHttpError or ApiOutcomeUnknownError was already thrown above, do not log a second critical network error
    if (err instanceof ApiHttpError || err instanceof ApiOutcomeUnknownError) {
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
        if (!isReadOnlyMethod && !isAuthOrHealth) {
          throw new ApiOutcomeUnknownError(
            UNKNOWN_OUTCOME_STANDARD_MSG,
            resolvedIdempotencyKey || undefined
          );
        }
        throw new Error(
          `Request timed out after ${timeoutMs / 1000}s connecting to backend.`
        );
      }
      if (category === 'CORS_RESTRICTION') {
        throw new Error(
          `CORS Error: Backend server did not allow connection from ${typeof window !== 'undefined' ? window.location.origin : 'this origin'}.`
        );
      }
      if (category === 'BACKEND_UNREACHABLE_OR_TIMEOUT') {
        // For business mutations, a dropped connection after fetch dispatch has an UNKNOWN outcome
        // (the backend may already have received and committed the request). Preserve the nonce!
        if (!isReadOnlyMethod && !isAuthOrHealth && resolvedIdempotencyKey) {
          throw new ApiOutcomeUnknownError(
            UNKNOWN_OUTCOME_STANDARD_MSG,
            resolvedIdempotencyKey
          );
        }
        throw new Error(
          'Unable to reach backend API server. Service is offline or unreachable.'
        );
      }
      throw err;
    }
    throw new Error('An unexpected network or client error occurred.');
  } finally {
    if (flightKey) {
      inflightMutationKeys.delete(flightKey);
    }
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
      ? 'Render backend is offline or unreachable (x-render-routing: no-server). Fail-closed lock active.'
      : err instanceof Error
      ? err.message
      : 'Backend unreachable. Fail-closed lock active.';

    return {
      status: 'unreachable',
      google_sheets_connected: false,
      persistent_writes_enabled: false,
      spreadsheet_id_configured: false,
      service_account_configured: false,
      last_connection_error: msg,
      allow_in_memory_fallback: false,
      backend: {
        status: 'UNREACHABLE',
        service: 'kawad-swad-erp-api',
        version: '2.1.0',
      },
      google_sheets: {
        status: 'DISCONNECTED',
        connected: false,
        persistent_writes_enabled: false,
        message: 'Backend or Google Sheets unavailable. All governed writes are blocked (fail closed).',
      },
      required_sheets: {
        status: 'UNAVAILABLE',
        total_managed_tabs: 255,
      },
    };
  }
}

export interface RawMaterialSummary {
  raw_material_id?: string;
  material_id: string;
  material_name: string;
  category: string;
  unit: string;
  opening_stock?: number;
  baseline_stock: number;
  recorded_opening_stock?: number;
  opening_stock_verified?: boolean;
  verification_status?: 'UNVERIFIED' | 'CONFIRMED' | string;
  verified_physical_stock?: number | null;
  verified_by?: string;
  verified_at?: string;
  unverified_opening_warning?: string;
  total_received: number;
  total_consumed: number;
  total_adjusted: number;
  available_stock: number;
  confirmed_available_stock?: number;
  latest_landed_rate: number;
}

export interface RawMaterialOpeningVerificationInput {
  raw_material_id: string;
  physical_count: number;
  confirm_physical_count: boolean;
  reason: string;
  verified_date?: string;
  idempotency_key?: string;
}

export interface RawMaterialOpeningVerificationResult {
  status: string;
  raw_material_id: string;
  material_name: string;
  unit: string;
  recorded_opening_stock: number;
  previous_available_stock: number;
  verified_physical_stock: number;
  confirmed_available_stock?: number;
  variance: number;
  opening_stock_verified: boolean;
  verification_status: string;
  verified_by: string;
  verified_at: string;
  raw_material_txn_id?: string;
  ledger_id: string;
  is_replay?: boolean;
  message: string;
}

export interface RecipeMappingAuditResponse {
  summary: {
    total_products: number;
    mapped_approved: number;
    mapped_draft: number;
    ambiguous: number;
    unmapped: number;
  };
  mappings: Array<{
    product_id: string;
    sku: string;
    product_name: string;
    pack_weight_g: number | string;
    active: boolean;
    explicit_recipe_id: string;
    resolved_recipe_id: string | null;
    resolved_recipe_name: string | null;
    recipe_approved: boolean;
    mapping_source: string | null;
    status: string;
    detail: string;
    candidates?: string[];
  }>;
}

export interface PackagingDiscrepanciesSummary {
  historical_unresolved_count: number;
  historical_unresolved_kg: number;
  pending_review_count: number;
  pending_review_kg: number;
  approved_discrepancy_count: number;
  historical_unresolved: Record<string, any>[];
  pending_review: Record<string, any>[];
  approved_discrepancy: Record<string, any>[];
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
  idempotency_key?: string;
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

export async function verifyRawMaterialOpeningStock(
  data: RawMaterialOpeningVerificationInput,
  idempotencyKey?: string
): Promise<RawMaterialOpeningVerificationResult> {
  return apiRequest<RawMaterialOpeningVerificationResult>('/api/production/raw-materials/verify-opening-stock', {
    method: 'POST',
    body: JSON.stringify(data),
    idempotencyKey: idempotencyKey || data.idempotency_key,
  });
}

export async function getRecipeMappingAudit(): Promise<RecipeMappingAuditResponse> {
  return apiRequest<RecipeMappingAuditResponse>('/api/production/recipes/mapping-audit', { silent: true });
}

export async function getPackagingDiscrepanciesSummary(): Promise<PackagingDiscrepanciesSummary> {
  return apiRequest<PackagingDiscrepanciesSummary>('/api/production/packaging/discrepancies-summary', { silent: true });
}

export async function approvePackagingDiscrepancy(
  packagingId: string,
  explanation: string,
  idempotencyKey?: string
): Promise<Record<string, any>> {
  return apiRequest<Record<string, any>>(
    `/api/production/packaging/${encodeURIComponent(packagingId)}/approve-discrepancy`,
    {
      method: 'POST',
      body: JSON.stringify({ explanation }),
      idempotencyKey,
    }
  );
}

export async function receiveRawMaterial(
  data: RawMaterialReceiveInput,
  idempotencyKey?: string
): Promise<RawMaterialReceiveResult> {
  return apiRequest<RawMaterialReceiveResult>('/api/production/raw-materials/receive', {
    method: 'POST',
    body: JSON.stringify(data),
    idempotencyKey: idempotencyKey || data.idempotency_key,
  });
}

export interface DalMillingInput {
  source_material_id: string;
  input_quantity_kg: number;
  flour_output_kg: number;
  milling_expenses?: number;
  milling_date?: string;
  batch_reference?: string;
  idempotency_key?: string;
  notes?: string;
}

export interface DalMillingResult {
  success: boolean;
  status: string;
  milling_batch_id: string;
  input_txn_id: string;
  output_txn_id: string;
  source_material_id: string;
  source_material_name: string;
  input_quantity_kg: number;
  target_flour_id: string;
  target_flour_name: string;
  flour_output_kg: number;
  processing_loss_kg: number;
  loss_percentage: number;
  source_unit_rate: number;
  milling_expenses: number;
  total_flour_cost: number;
  flour_unit_cost: number;
  new_whole_stock: number;
  new_flour_stock: number;
  is_replay: boolean;
  message: string;
}

export interface DalMillingHistoryItem {
  milling_batch_id: string;
  milling_date: string;
  source_material_id: string;
  source_material_name: string;
  input_quantity_kg: number;
  target_flour_id: string;
  target_flour_name: string;
  flour_output_kg: number;
  processing_loss_kg: number;
  loss_percentage: number;
  source_unit_rate: number;
  milling_expenses: number;
  total_flour_cost: number;
  flour_unit_cost: number;
  batch_reference: string;
  created_by: string;
  notes: string;
}

export async function recordMillingBatch(
  data: DalMillingInput,
  idempotencyKey?: string
): Promise<DalMillingResult> {
  return apiRequest<DalMillingResult>('/api/production/milling/record', {
    method: 'POST',
    body: JSON.stringify(data),
    idempotencyKey: idempotencyKey || data.idempotency_key,
  });
}

export async function getMillingHistory(): Promise<DalMillingHistoryItem[]> {
  return apiRequest<DalMillingHistoryItem[]>('/api/production/milling/history');
}

// -------------------------------------------------------------
// Double-Entry General Ledger Accounting Endpoints
// -------------------------------------------------------------

export interface AccountMaster {
  account_code: string;
  account_name: string;
  account_type: 'ASSET' | 'LIABILITY' | 'EQUITY' | 'REVENUE' | 'EXPENSE';
  normal_balance: 'DEBIT' | 'CREDIT';
  is_reconciled: string;
  active: string;
  description: string;
}

export interface TrialBalanceRow {
  account_code: string;
  account_name: string;
  account_type: string;
  total_debit: number;
  total_credit: number;
  net_debit: number;
  net_credit: number;
}

export interface TrialBalanceResult {
  as_of_date: string;
  is_balanced: boolean;
  grand_total_debit: number;
  grand_total_credit: number;
  difference: number;
  rows: TrialBalanceRow[];
  lines?: TrialBalanceRow[];
}

export interface ProfitAndLossResult {
  period_start: string;
  period_end: string;
  total_revenue: number;
  total_cogs: number;
  gross_profit: number;
  gross_margin_percentage: number;
  total_operating_expenses: number;
  net_operating_profit: number;
  net_margin_percentage: number;
  revenue_breakdown: TrialBalanceRow[];
  cogs_breakdown: TrialBalanceRow[];
  operating_expenses_breakdown: TrialBalanceRow[];
}

export interface BalanceSheetResult {
  as_of_date: string;
  is_balanced: boolean;
  total_assets: number;
  total_liabilities: number;
  total_equity: number;
  current_period_net_profit: number;
  total_liabilities_and_equity: number;
  balance_difference: number;
  assets_breakdown: TrialBalanceRow[];
  liabilities_breakdown: TrialBalanceRow[];
  equity_breakdown: TrialBalanceRow[];
}

export interface JournalLineItem {
  line_id: string;
  journal_id: string;
  line_no: number;
  account_code: string;
  account_name: string;
  debit_amount: number;
  credit_amount: number;
  entity_type: string;
  entity_id: string;
  notes: string;
}

export interface JournalVoucherItem {
  journal_id: string;
  journal_date: string;
  voucher_type: string;
  reference_type: string;
  reference_id: string;
  narration: string;
  total_debit: number;
  total_credit: number;
  posted_by: string;
  posted_at: string;
  status: string;
  reversal_of_id?: string;
  lines: JournalLineItem[];
}

export async function fetchChartOfAccounts(): Promise<AccountMaster[]> {
  return apiRequest<AccountMaster[]>('/api/accounting/chart-of-accounts');
}

export async function fetchTrialBalance(asOfDate?: string): Promise<TrialBalanceResult> {
  const query = asOfDate ? `?as_of_date=${encodeURIComponent(asOfDate)}` : '';
  return apiRequest<TrialBalanceResult>(`/api/accounting/trial-balance${query}`);
}

export async function fetchProfitAndLoss(startDate?: string, endDate?: string): Promise<ProfitAndLossResult> {
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<ProfitAndLossResult>(`/api/accounting/profit-and-loss${qs}`);
}

export async function fetchBalanceSheet(asOfDate?: string): Promise<BalanceSheetResult> {
  const query = asOfDate ? `?as_of_date=${encodeURIComponent(asOfDate)}` : '';
  return apiRequest<BalanceSheetResult>(`/api/accounting/balance-sheet${query}`);
}

export async function fetchJournalVouchers(voucherType?: string, limit = 50): Promise<JournalVoucherItem[]> {
  const params = new URLSearchParams();
  if (voucherType) params.set('voucher_type', voucherType);
  if (limit) params.set('limit', String(limit));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<JournalVoucherItem[]>(`/api/accounting/vouchers${qs}`);
}

export async function reverseJournalVoucherApi(
  journalId: string,
  reason: string,
  idempotencyKey?: string
): Promise<JournalVoucherItem> {
  return apiRequest<JournalVoucherItem>(`/api/accounting/vouchers/${encodeURIComponent(journalId)}/reverse`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
    idempotencyKey,
  });
}

export interface ReconcileResult {
  status: string;
  dry_run: boolean;
  missing_count: number;
  unposted_count?: number;
  failed_count?: number;
  incomplete_count?: number;
  duplicate_reference_count?: number;
  reconciled_count: number;
  error_count: number;
  missing_events: Array<{
    source_table: string;
    reference_type: string;
    reference_id: string;
    date: string;
    description: string;
    issue_type?: string;
    journal_id?: string;
    failure_reason?: string;
  }>;
  unposted_events?: Array<{
    source_table: string;
    reference_type: string;
    reference_id: string;
    date: string;
    description: string;
    issue_type?: string;
    journal_id?: string;
    failure_reason?: string;
  }>;
  failed_vouchers?: Array<{
    source_table: string;
    reference_type: string;
    reference_id: string;
    date: string;
    description: string;
    issue_type?: string;
    journal_id?: string;
    failure_reason?: string;
  }>;
  duplicate_references?: Array<{
    reference_key: string;
    voucher_count: number;
    journal_ids: string[];
  }>;
  reconciled_events: Array<{
    source_table: string;
    reference_type: string;
    reference_id: string;
    voucher_id?: string;
  }>;
  errors: Array<{
    source_table: string;
    reference_type: string;
    reference_id: string;
    error: string;
  }>;
}

export interface OpeningBalanceProposal {
  status: string;
  balance_check: string;
  total_assets: number;
  total_liabilities: number;
  owner_equity: number;
  total_debits: number;
  total_credits: number;
  proposed_lines: Array<{
    account_code: string;
    account_name: string;
    debit: number;
    credit: number;
  }>;
  note: string;
}

export async function fetchReconciliationReport(): Promise<ReconcileResult> {
  return apiRequest<ReconcileResult>('/api/accounting/reconcile');
}

export async function executeReconciliation(
  dryRun = false,
  confirmLiveBackfill = true,
  idempotencyKey?: string
): Promise<ReconcileResult> {
  return apiRequest<ReconcileResult>(`/api/accounting/reconcile?dry_run=${dryRun}&confirm_live_backfill=${confirmLiveBackfill}`, {
    method: 'POST',
    idempotencyKey,
  });
}

export async function fetchOpeningBalanceProposal(): Promise<OpeningBalanceProposal> {
  return apiRequest<OpeningBalanceProposal>('/api/accounting/opening-balances/proposal');
}

export async function recordSalePaymentApi(
  saleId: string,
  payment: { amount: number; payment_method: string; reference_number?: string; notes?: string; idempotency_key?: string },
  idempotencyKey?: string
): Promise<{ ok: boolean; payment_id: string; sale_id: string; amount_paid: number; remaining_balance: number; payment_status: string }> {
  return apiRequest(`/api/sales/${encodeURIComponent(saleId)}/payments`, {
    method: 'POST',
    body: JSON.stringify(payment),
    idempotencyKey: idempotencyKey || payment.idempotency_key,
  });
}

// -------------------------------------------------------------
// Purchasing & Procurement API
// -------------------------------------------------------------

export async function getSuppliers(): Promise<Supplier[]> {
  return apiRequest<Supplier[]>('/api/purchasing/suppliers');
}

export async function createSupplier(
  supplier: Partial<Supplier>,
  idempotencyKey?: string
): Promise<Supplier> {
  return apiRequest<Supplier>('/api/purchasing/suppliers', {
    method: 'POST',
    body: JSON.stringify(supplier),
    idempotencyKey,
  });
}

export async function updateSupplier(
  supplierId: string,
  supplier: Partial<Supplier>,
  idempotencyKey?: string
): Promise<Supplier> {
  return apiRequest<Supplier>(`/api/purchasing/suppliers/${encodeURIComponent(supplierId)}`, {
    method: 'PUT',
    body: JSON.stringify(supplier),
    idempotencyKey,
  });
}

export async function getPurchaseOrders(status?: string): Promise<PurchaseOrder[]> {
  const url = status ? `/api/purchasing/orders?status=${encodeURIComponent(status)}` : '/api/purchasing/orders';
  return apiRequest<PurchaseOrder[]>(url);
}

export async function createPurchaseOrder(payload: {
  supplier_id: string;
  order_date: string;
  expected_delivery_date?: string;
  notes?: string;
  idempotency_key?: string;
  items: Array<{
    material_id?: string;
    raw_material_id?: string;
    material_name: string;
    ordered_quantity: number;
    unit: string;
    unit_price: number;
    gst_rate?: number;
    tax_rate?: number;
    notes?: string;
  }>;
}, idempotencyKey?: string): Promise<PurchaseOrder> {
  const normalized = {
    ...payload,
    items: payload.items.map((item) => ({
      ...item,
      raw_material_id: item.raw_material_id || item.material_id || 'RM-WHOLE-MOONG-DAL',
      material_name: item.material_name,
      ordered_quantity: Number(item.ordered_quantity),
      unit: item.unit || 'kg',
      unit_price: Number(item.unit_price),
      tax_rate: item.tax_rate !== undefined ? Number(item.tax_rate) : (item.gst_rate !== undefined ? Number(item.gst_rate) : 0),
    })),
  };
  return apiRequest<PurchaseOrder>('/api/purchasing/orders', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function cancelPurchaseOrder(
  orderId: string,
  reason?: string,
  idempotencyKey?: string
): Promise<{ ok: boolean; status: string; order_id: string }> {
  return apiRequest(`/api/purchasing/orders/${encodeURIComponent(orderId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
    idempotencyKey,
  });
}

export async function getGoodsReceipts(): Promise<GoodsReceipt[]> {
  return apiRequest<GoodsReceipt[]>('/api/purchasing/receipts');
}

export async function createGoodsReceipt(payload: {
  supplier_id: string;
  receipt_date: string;
  po_id?: string;
  vendor_delivery_challan?: string;
  delivery_challan?: string;
  invoice_reference?: string;
  vehicle_number?: string;
  quality_status?: string;
  notes?: string;
  idempotency_key?: string;
  items: Array<{
    po_item_id?: string;
    material_id?: string;
    raw_material_id?: string;
    material_name: string;
    unit: string;
    delivered_quantity?: number;
    accepted_quantity?: number;
    rejected_quantity?: number;
    received_quantity?: number;
    unit_price?: number;
    unit_rate?: number;
    rejection_reason?: string;
    tax_rate?: number;
    gst_treatment?: string;
    storage_location?: string;
    batch_reference?: string;
    qc_status?: string;
    notes?: string;
  }>;
}, idempotencyKey?: string): Promise<GoodsReceipt> {
  const effectiveKey = (idempotencyKey || payload.idempotency_key || '').trim();
  const deterministicSuffix = (
    effectiveKey || `${payload.supplier_id || 'SUP'}-${payload.receipt_date || 'GRN'}`
  )
    .replace(/[^A-Za-z0-9]/g, '')
    .slice(-8)
    .toUpperCase();
  const invoiceRef =
    payload.invoice_reference ||
    payload.vendor_delivery_challan ||
    payload.delivery_challan ||
    `CH-${deterministicSuffix || 'REF'}`;
  const normalized = {
    ...payload,
    invoice_reference: invoiceRef,
    delivery_challan: payload.delivery_challan || payload.vendor_delivery_challan || invoiceRef,
    quality_status: payload.quality_status || 'ACCEPTED',
    items: payload.items.map((item) => {
      const deliv = Number(item.delivered_quantity ?? item.received_quantity ?? 0);
      const rej = Number(item.rejected_quantity ?? 0);
      const acc = Number(item.accepted_quantity ?? (deliv >= rej ? deliv - rej : deliv));
      const rate = Number(item.unit_rate ?? item.unit_price ?? 0);
      return {
        ...item,
        po_item_id: item.po_item_id || '',
        raw_material_id: item.raw_material_id || item.material_id || 'RM-WHOLE-MOONG-DAL',
        material_name: item.material_name,
        delivered_quantity: deliv,
        accepted_quantity: acc,
        rejected_quantity: rej,
        unit: item.unit || 'kg',
        unit_rate: rate,
        unit_price: rate,
        rejection_reason: item.rejection_reason || '',
      };
    }),
  };
  return apiRequest<GoodsReceipt>('/api/purchasing/receipts', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function getSupplierBills(status?: string): Promise<SupplierBill[]> {
  const url = status ? `/api/purchasing/bills?status=${encodeURIComponent(status)}` : '/api/purchasing/bills';
  return apiRequest<SupplierBill[]>(url);
}

export async function createSupplierBill(payload: {
  supplier_id: string;
  bill_number: string;
  bill_date: string;
  due_date?: string;
  po_id?: string;
  grn_id?: string;
  receipt_id?: string;
  subtotal?: number;
  tax_amount?: number;
  taxable_amount: number;
  cgst_amount?: number;
  sgst_amount?: number;
  igst_amount?: number;
  freight_amount?: number;
  other_expenses?: number;
  total_amount: number;
  notes?: string;
  idempotency_key?: string;
}, idempotencyKey?: string): Promise<SupplierBill> {
  const normalized = {
    ...payload,
    receipt_id: payload.receipt_id || payload.grn_id || '',
    subtotal: Number(payload.subtotal ?? payload.taxable_amount ?? 0),
    tax_amount: Number(
      payload.tax_amount ??
        ((payload.cgst_amount || 0) + (payload.sgst_amount || 0) + (payload.igst_amount || 0))
    ),
  };
  return apiRequest<SupplierBill>('/api/purchasing/bills', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function getSupplierPayments(): Promise<SupplierPayment[]> {
  return apiRequest<SupplierPayment[]>('/api/purchasing/payments');
}

export async function recordSupplierPayment(
  payload: {
    supplier_id: string;
    bill_id?: string;
    payment_date: string;
    payment_mode: 'CASH' | 'BANK' | 'UPI' | 'NEFT';
    payment_method?: string;
    amount: number;
    reference_no?: string;
    reference_number?: string;
    idempotency_key?: string;
    notes?: string;
  },
  idempotencyKey?: string
): Promise<SupplierPayment> {
  const methodMap: Record<string, string> = {
    BANK: 'BANK_TRANSFER',
    NEFT: 'NEFT',
  };
  const externalRef = (payload.reference_number || payload.reference_no || '').trim();
  const effectiveIdempKey = idempotencyKey || payload.idempotency_key;
  const normalized = {
    supplier_id: payload.supplier_id,
    bill_id: (payload.bill_id || '').trim(),
    payment_date: payload.payment_date,
    payment_method:
      payload.payment_method ||
      methodMap[payload.payment_mode] ||
      payload.payment_mode ||
      'BANK_TRANSFER',
    amount: Number(payload.amount || 0),
    reference_number: externalRef,
    idempotency_key: effectiveIdempKey,
    notes: payload.notes || '',
  };
  return apiRequest<SupplierPayment>('/api/purchasing/payments', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: effectiveIdempKey,
  });
}

export async function applySupplierAdvance(
  paymentId: string,
  payload: {
    bill_id: string;
    amount?: number;
    idempotency_key?: string;
    notes?: string;
  },
  idempotencyKey?: string
): Promise<{
  ok: boolean;
  payment: SupplierPayment;
  bill: SupplierBill;
  applied_amount: number;
  remaining_advance: number;
  is_replay?: boolean;
}> {
  const effectiveIdempKey = idempotencyKey || payload.idempotency_key;
  return apiRequest(`/api/purchasing/payments/${encodeURIComponent(paymentId)}/apply`, {
    method: 'POST',
    body: JSON.stringify({ ...payload, idempotency_key: effectiveIdempKey }),
    idempotencyKey: effectiveIdempKey,
  });
}

export async function getSupplierReturns(): Promise<SupplierReturn[]> {
  return apiRequest<SupplierReturn[]>('/api/purchasing/returns');
}

export async function createSupplierReturn(payload: {
  supplier_id: string;
  grn_id?: string;
  receipt_id?: string;
  return_date: string;
  reason: string;
  notes?: string;
  idempotency_key?: string;
  items: Array<{
    material_id: string;
    raw_material_id?: string;
    material_name: string;
    returned_quantity: number;
    quantity?: number;
    unit: string;
    unit_price: number;
    unit_rate?: number;
    reason?: string;
    notes?: string;
  }>;
}, idempotencyKey?: string): Promise<SupplierReturn> {
  const normalized = {
    ...payload,
    receipt_id: payload.receipt_id || payload.grn_id || '',
    items: payload.items.map((item) => ({
      ...item,
      raw_material_id: item.raw_material_id || item.material_id,
      quantity: Number(item.quantity ?? item.returned_quantity ?? 0),
      unit_rate: Number(item.unit_rate ?? item.unit_price ?? 0),
      reason:
        (item.reason || payload.reason || 'Supplier material return').trim().length >= 3
          ? (item.reason || payload.reason || 'Supplier material return').trim()
          : 'Supplier return',
    })),
  };
  return apiRequest<SupplierReturn>('/api/purchasing/returns', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function getPurchasingSummary(): Promise<{
  total_suppliers: number;
  open_pos: number;
  unpaid_bills: number;
  total_payables: number;
  total_advances?: number;
  net_payable?: number;
}> {
  return apiRequest('/api/purchasing/summary');
}

// -------------------------------------------------------------
// Quality, Lots & Returns API
// -------------------------------------------------------------

export async function getQualityChecks(entityType?: string): Promise<QualityCheck[]> {
  const url = entityType ? `/api/quality/checks?entity_type=${encodeURIComponent(entityType)}` : '/api/quality/checks';
  return apiRequest<QualityCheck[]>(url);
}

export async function createQualityCheck(payload: {
  check_type: 'RAW_MATERIAL' | 'IN_PROCESS' | 'FINISHED_GOODS';
  entity_type: string;
  entity_id: string;
  reference_type?: string;
  reference_id?: string;
  product_or_material_id?: string;
  item_name: string;
  decision: 'PASS' | 'FAIL' | 'HOLD';
  defect_details?: string;
  corrective_action?: string;
  notes?: string;
  idempotency_key?: string;
}, idempotencyKey?: string): Promise<QualityCheck> {
  const normalized = {
    ...payload,
    reference_type: payload.reference_type || payload.entity_type || 'PRODUCT_LOT',
    reference_id: payload.reference_id || payload.entity_id || 'LOT-REF',
    product_or_material_id: payload.product_or_material_id || payload.entity_id || 'PRD-UNKNOWN',
  };
  return apiRequest<QualityCheck>('/api/quality/checks', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function getProductLots(status?: string): Promise<ProductLot[]> {
  const url = status ? `/api/quality/lots?status=${encodeURIComponent(status)}` : '/api/quality/lots';
  return apiRequest<ProductLot[]>(url);
}

export async function createProductLot(payload: {
  product_id: string;
  product_name: string;
  initial_quantity: number;
  unit: string;
  expiry_date?: string;
  production_id?: string;
  packaging_id?: string;
  notes?: string;
  idempotency_key?: string;
}, idempotencyKey?: string): Promise<ProductLot> {
  return apiRequest<ProductLot>('/api/quality/lots', {
    method: 'POST',
    body: JSON.stringify(payload),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function updateLotStatus(
  lotId: string,
  qualityStatus: 'RELEASED' | 'QUARANTINE' | 'REJECTED' | 'RECALLED',
  holdReason?: string,
  idempotencyKey?: string
): Promise<ProductLot> {
  return apiRequest<ProductLot>(`/api/quality/lots/${encodeURIComponent(lotId)}/status`, {
    method: 'POST',
    body: JSON.stringify({ quality_status: qualityStatus, hold_reason: holdReason }),
    idempotencyKey,
  });
}

export async function getLotMovements(lotId?: string): Promise<LotMovement[]> {
  if (!lotId) return [];
  return apiRequest<LotMovement[]>(`/api/quality/lots/${encodeURIComponent(lotId)}/movements`);
}

export async function getCustomerReturns(): Promise<CustomerReturn[]> {
  return apiRequest<CustomerReturn[]>('/api/quality/customer-returns');
}

export async function createCustomerReturn(payload: {
  sale_id: string;
  customer_id: string;
  customer_name: string;
  return_date: string;
  disposition: 'SCRAP' | 'RESTOCK' | 'PENDING_INSPECTION';
  notes?: string;
  idempotency_key?: string;
  items: Array<{
    product_id: string;
    sku: string;
    product_name: string;
    quantity: number;
    unit: string;
    unit_price: number;
    refund_amount?: number;
    reason: string;
    notes?: string;
  }>;
}, idempotencyKey?: string): Promise<CustomerReturn> {
  const normalized = {
    ...payload,
    items: payload.items.map((item) => ({
      ...item,
      refund_amount: Number(item.refund_amount ?? (item.quantity * item.unit_price).toFixed(2)),
    })),
  };
  return apiRequest<CustomerReturn>('/api/quality/customer-returns', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function getComplaintsRecalls(status?: string): Promise<ComplaintRecall[]> {
  const url = status ? `/api/quality/complaints?status=${encodeURIComponent(status)}` : '/api/quality/complaints';
  return apiRequest<ComplaintRecall[]>(url);
}

export async function createComplaintOrRecall(payload: {
  report_type: 'COMPLAINT' | 'RECALL';
  product_id: string;
  lot_id?: string;
  customer_id?: string;
  customer_name?: string;
  quantity_affected: number;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  description: string;
  notes?: string;
  idempotency_key?: string;
}, idempotencyKey?: string): Promise<ComplaintRecall> {
  return apiRequest<ComplaintRecall>('/api/quality/complaints', {
    method: 'POST',
    body: JSON.stringify(payload),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function closeComplaint(
  complaintId: string,
  data: { investigation?: string; corrective_action?: string; notes?: string },
  idempotencyKey?: string
): Promise<ComplaintRecall> {
  const rawAction = (data.corrective_action || data.investigation || data.notes || 'Resolved and closed').trim();
  const action = rawAction.length >= 5 ? rawAction : `${rawAction} (Closed)`;
  return apiRequest<ComplaintRecall>(
    `/api/quality/complaints/${encodeURIComponent(complaintId)}/close?corrective_action=${encodeURIComponent(action)}`,
    {
      method: 'POST',
      idempotencyKey,
    }
  );
}

export async function getQualitySummary(): Promise<{
  total_checks: number;
  quarantined_lots: number;
  open_returns: number;
  open_complaints: number;
}> {
  return apiRequest('/api/quality/summary');
}

// -------------------------------------------------------------
// Dal Milling & Stock Movements API
// -------------------------------------------------------------

export async function getMillingBatches(): Promise<MillingBatch[]> {
  return apiRequest<MillingBatch[]>('/api/production/milling');
}

export async function executeDalMilling(payload: {
  source_material_id: string;
  input_quantity_kg: number;
  flour_output_kg: number;
  milling_expenses?: number;
  batch_reference?: string;
  idempotency_key?: string;
  notes?: string;
}, idempotencyKey?: string): Promise<DalMillingResult> {
  return apiRequest<DalMillingResult>('/api/production/milling/record', {
    method: 'POST',
    body: JSON.stringify(payload),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function adjustRawMaterialStock(payload: {
  material_id?: string;
  item_id?: string;
  adjusted_quantity?: number;
  quantity_change?: number;
  unit?: string;
  adjustment_type?: 'OPENING_BALANCE' | 'ADJUSTMENT' | 'RECONCILIATION';
  reason: string;
  reference_id?: string;
  authorized_by?: string;
  idempotency_key?: string;
}, idempotencyKey?: string): Promise<{ status: string; txn_id: string; material_id: string; quantity_change: number }> {
  const normalized = {
    item_type: 'RAW_MATERIAL',
    item_id: (payload.item_id || payload.material_id || '').trim(),
    adjustment_type: payload.adjustment_type || 'ADJUSTMENT',
    quantity_change: Number(payload.quantity_change ?? payload.adjusted_quantity ?? 0),
    unit: payload.unit || 'kg',
    reason: payload.reason,
    reference_id: payload.reference_id || '',
  };
  return apiRequest('/api/production/raw-materials/adjustment', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export async function adjustFinishedGoodsStock(payload: {
  product_id?: string;
  item_id?: string;
  adjusted_packets?: number;
  quantity_change?: number;
  unit?: string;
  adjustment_type?: 'OPENING_BALANCE' | 'ADJUSTMENT' | 'RECONCILIATION';
  reason: string;
  reference_id?: string;
  location?: string;
  authorized_by?: string;
  idempotency_key?: string;
}, idempotencyKey?: string): Promise<{ status: string; movement_id: string; product_id: string; quantity_change: number }> {
  const normalized = {
    item_type: 'FINISHED_GOODS',
    item_id: (payload.item_id || payload.product_id || '').trim(),
    adjustment_type: payload.adjustment_type || 'ADJUSTMENT',
    quantity_change: Number(payload.quantity_change ?? payload.adjusted_packets ?? 0),
    unit: payload.unit || 'PACKET',
    reason: payload.reason,
    reference_id: payload.reference_id || '',
  };
  return apiRequest('/api/production/finished-goods/adjustment', {
    method: 'POST',
    body: JSON.stringify(normalized),
    idempotencyKey: idempotencyKey || payload.idempotency_key,
  });
}

export interface StockMovementItem {
  id: string;
  date: string;
  type: string;
  category: 'RAW_MATERIAL' | 'BULK_WIP' | 'FINISHED_GOODS';
  item_id: string;
  quantity: number;
  unit: string;
  reference_type: string;
  reference_id: string;
  notes?: string;
}

export async function getUnifiedStockMovements(): Promise<StockMovementItem[]> {
  return apiRequest<StockMovementItem[]>('/api/production/stock-movements');
}

// -------------------------------------------------------------
// Sales Orders (Draft -> Confirm) & Dispatch
// -------------------------------------------------------------

export async function getSalesOrders(): Promise<any[]> {
  return apiRequest('/api/sales/orders');
}

export async function createSalesOrder(payload: any, idempotencyKey?: string): Promise<any> {
  return apiRequest('/api/sales/orders', {
    method: 'POST',
    body: JSON.stringify(payload),
    idempotencyKey: idempotencyKey || payload?.idempotency_key || payload?.nonce,
  });
}

export async function confirmSalesOrder(saleId: string, idempotencyKey?: string): Promise<any> {
  return apiRequest(`/api/sales/orders/${encodeURIComponent(saleId)}/confirm`, {
    method: 'POST',
    idempotencyKey,
  });
}

export async function getDispatchSummary(): Promise<any> {
  return apiRequest('/api/sales/dispatch-summary');
}

// -------------------------------------------------------------
// Extended Accounting & Management Reports
// -------------------------------------------------------------

export async function getDebtorsBalances(): Promise<{ as_of_date: string; debtors: DebtorItem[]; total_receivables: number }> {
  const res = await apiRequest<DebtorItem[] | { as_of_date?: string; debtors?: DebtorItem[]; total_receivables?: number }>('/api/accounting/debtors');
  const debtors = Array.isArray(res) ? res : (res?.debtors || []);
  return {
    as_of_date: Array.isArray(res) ? new Date().toISOString().slice(0, 10) : (res?.as_of_date || ''),
    debtors,
    total_receivables: Array.isArray(res)
      ? debtors.reduce((sum, item) => sum + Number(item.outstanding_balance || 0), 0)
      : Number(res?.total_receivables || 0),
  };
}

export async function getCreditorsBalances(): Promise<{ as_of_date: string; creditors: CreditorItem[]; total_payables: number }> {
  const res = await apiRequest<CreditorItem[] | { as_of_date?: string; creditors?: CreditorItem[]; total_payables?: number }>('/api/accounting/creditors');
  const creditors = Array.isArray(res) ? res : (res?.creditors || []);
  return {
    as_of_date: Array.isArray(res) ? new Date().toISOString().slice(0, 10) : (res?.as_of_date || ''),
    creditors,
    total_payables: Array.isArray(res)
      ? creditors.reduce((sum, item) => sum + Number(item.outstanding_payable || 0), 0)
      : Number(res?.total_payables || 0),
  };
}

export async function getCashBankReport(): Promise<CashBankReport> {
  return apiRequest<CashBankReport>('/api/accounting/cash-bank');
}

export async function getGstSummaryReport(startDate?: string, endDate?: string): Promise<GstSummaryReport> {
  let url = '/api/accounting/gst-summary';
  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const q = params.toString();
  if (q) url += `?${q}`;
  return apiRequest<GstSummaryReport>(url);
}

export async function getAccountingPeriods(): Promise<AccountingPeriod[]> {
  return apiRequest<AccountingPeriod[]>('/api/accounting/periods');
}

export async function closeAccountingPeriod(
  periodId: string,
  idempotencyKey?: string
): Promise<{ ok: boolean; status: string; period: AccountingPeriod }> {
  return apiRequest(`/api/accounting/periods/${encodeURIComponent(periodId)}/close`, {
    method: 'POST',
    idempotencyKey,
  });
}

// -------------------------------------------------------------
// Van Loading Pass API (Phase 2A.1)
// -------------------------------------------------------------

export async function getVanLoadingPasses(params?: { salesman_id?: string; date?: string; status?: string }): Promise<VanLoadingPass[]> {
  let url = '/api/stock/loading-passes';
  if (params) {
    const q = new URLSearchParams();
    if (params.salesman_id) q.set('salesman_id', params.salesman_id);
    if (params.date) q.set('date', params.date);
    if (params.status) q.set('status', params.status);
    const qs = q.toString();
    if (qs) url += `?${qs}`;
  }
  return apiRequest<VanLoadingPass[]>(url);
}

export async function getVanLoadingPass(passIdOrNumber: string): Promise<VanLoadingPass> {
  return apiRequest<VanLoadingPass>(`/api/stock/loading-passes/${encodeURIComponent(passIdOrNumber)}`);
}

export async function createVanLoadingPass(
  payload: VanLoadingPassCreate,
  idempotencyKey?: string
): Promise<VanLoadingPass> {
  return apiRequest<VanLoadingPass>('/api/stock/loading-passes', {
    method: 'POST',
    body: JSON.stringify(payload),
    idempotencyKey,
  });
}

export async function acceptVanLoadingPass(
  passIdOrNumber: string,
  notes?: string,
  idempotencyKey?: string
): Promise<VanLoadingPass> {
  return apiRequest<VanLoadingPass>(`/api/stock/loading-passes/${encodeURIComponent(passIdOrNumber)}/accept`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
    idempotencyKey,
  });
}

export async function reportVanLoadingDiscrepancy(
  passIdOrNumber: string,
  discrepancyNotes: string,
  idempotencyKey?: string
): Promise<VanLoadingPass> {
  return apiRequest<VanLoadingPass>(`/api/stock/loading-passes/${encodeURIComponent(passIdOrNumber)}/discrepancy`, {
    method: 'POST',
    body: JSON.stringify({ discrepancy_notes: discrepancyNotes }),
    idempotencyKey,
  });
}

export async function cancelVanLoadingPass(
  passIdOrNumber: string,
  notes?: string,
  idempotencyKey?: string
): Promise<VanLoadingPass> {
  return apiRequest<VanLoadingPass>(`/api/stock/loading-passes/${encodeURIComponent(passIdOrNumber)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
    idempotencyKey,
  });
}

// -------------------------------------------------------------
// Blueprint v2.1 /api/v2 Governed Operations, Policies & Official Reports
// -------------------------------------------------------------

export async function fetchV2Capabilities(): Promise<ErpCapabilitiesPayload> {
  return apiRequest<ErpCapabilitiesPayload>('/api/v2/meta/capabilities');
}

export async function fetchV2Policies(): Promise<{ policies: Record<string, PendingCaPolicy> }> {
  return apiRequest<{ policies: Record<string, PendingCaPolicy> }>('/api/v2/meta/policies');
}

export async function fetchV2SchemaRegistry(): Promise<SchemaRegistryPayload> {
  return apiRequest<SchemaRegistryPayload>('/api/v2/meta/schema-registry');
}

export async function updateV2Policy(
  policyKey: string,
  payload: { status: 'APPROVED' | 'PENDING_CA_APPROVAL'; value: unknown; notes?: string; nonce?: string }
): Promise<{ status?: string; ok?: boolean; policy: PendingCaPolicy; correlation_id?: string; allocated_id?: string }> {
  try {
    return await apiRequest<{ status?: string; ok?: boolean; policy: PendingCaPolicy; correlation_id?: string; allocated_id?: string }>(
      `/api/v2/meta/policies/${encodeURIComponent(policyKey)}`,
      {
        method: 'PUT',
        body: JSON.stringify(payload),
        idempotencyKey: payload.nonce,
        timeoutMs: 30000,
      }
    );
  } catch (err: unknown) {
    if (err instanceof ApiOutcomeUnknownError) {
      throw new ApiOutcomeUnknownError(
        UNKNOWN_OUTCOME_STANDARD_MSG,
        payload.nonce,
        err.correlationId
      );
    }
    throw err;
  }
}

export async function checkV2TransactionStatus(
  nonce: string,
  correlationId?: string
): Promise<TransactionStatusResponse> {
  const q = new URLSearchParams();
  if (correlationId) q.set('correlation_id', correlationId);
  const qs = q.toString();
  return apiRequest<TransactionStatusResponse>(
    `/api/v2/transactions/status/${encodeURIComponent(nonce)}${qs ? `?${qs}` : ''}`
  );
}

export async function fetchV2OfficialReport(
  reportSlug: 'trial-balance' | 'stock-status' | 'sales-receivables',
  params?: { period?: string; page?: number; page_size?: number }
): Promise<ReportTabPayload> {
  const q = new URLSearchParams();
  if (params?.period) q.set('period', params.period);
  if (params?.page) q.set('page', String(params.page));
  if (params?.page_size) q.set('page_size', String(params.page_size));
  const qs = q.toString();
  return apiRequest<ReportTabPayload>(`/api/v2/reports/${reportSlug}${qs ? `?${qs}` : ''}`);
}

export async function fetchV2Collection(
  endpointPath: string,
  params?: { page?: number; page_size?: number; search?: string; status?: string }
): Promise<PaginatedV2Response> {
  const q = new URLSearchParams();
  if (params?.page) q.set('page', String(params.page));
  if (params?.page_size) q.set('page_size', String(params.page_size));
  if (params?.search) q.set('search', params.search);
  if (params?.status) q.set('status', params.status);
  const qs = q.toString();
  const clean = endpointPath.startsWith('/api/v2/') ? endpointPath : `/api/v2/${endpointPath.replace(/^\/+/, '')}`;
  return apiRequest<PaginatedV2Response>(`${clean}${qs ? `?${qs}` : ''}`);
}

export async function postV2GovernedAction<T = Record<string, any>>(
  endpointPath: string,
  payload: Record<string, any> & { nonce: string }
): Promise<T> {
  const clean = endpointPath.startsWith('/api/v2/') ? endpointPath : `/api/v2/${endpointPath.replace(/^\/+/, '')}`;
  try {
    return await apiRequest<T>(clean, {
      method: 'POST',
      body: JSON.stringify(payload),
      idempotencyKey: payload.nonce,
      timeoutMs: 30000,
    });
  } catch (err: unknown) {
    if (err instanceof ApiOutcomeUnknownError) {
      throw new ApiOutcomeUnknownError(
        UNKNOWN_OUTCOME_STANDARD_MSG,
        payload.nonce,
        err.correlationId
      );
    }
    throw err;
  }
}

export async function createV2PurchaseOrder(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/procurement/purchase-orders', payload);
}

export async function createV2GoodsReceipt(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/procurement/goods-receipts', payload);
}

export async function fetchV2StoreLedger(params?: {
  ledger_type?: 'RAW_MATERIAL' | 'PRODUCTION_STOCK' | 'LOT_MOVEMENTS';
  page?: number;
  page_size?: number;
  search?: string;
}): Promise<PaginatedV2Response> {
  const q = new URLSearchParams();
  if (params?.ledger_type) q.set('ledger_type', params.ledger_type);
  if (params?.page) q.set('page', String(params.page));
  if (params?.page_size) q.set('page_size', String(params.page_size));
  if (params?.search) q.set('search', params.search);
  const qs = q.toString();
  return apiRequest<PaginatedV2Response>(`/api/v2/store/ledger${qs ? `?${qs}` : ''}`);
}

export async function createV2StockAdjustment(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/store/stock-adjustments', payload);
}

export async function createV2MillingBatch(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/milling/batches', payload);
}

export async function createV2ProductionBatch(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/production/batches', payload);
}

export async function createV2SalesOrder(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/sales/orders', payload);
}

export async function createV2SalesInvoice(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/sales/invoices', payload);
}

export async function createV2JournalVoucher(
  payload: Record<string, any> & { nonce: string }
): Promise<Record<string, any>> {
  return postV2GovernedAction('/api/v2/accounting/journals', payload);
}







