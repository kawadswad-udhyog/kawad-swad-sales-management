/**
 * Mission 51B-1R-F: Frontend UNKNOWN-Outcome Lock Persistence Safety &
 * Canonical Payload Fingerprint Enforcement.
 *
 * Guarantees:
 * 1. Persistence Safety (Phase 1):
 *    - Persists UNKNOWN / RECOVERY_REQUIRED lock to sessionStorage AND verifies
 *      immediate read-back integrity (nonce, scope, transactionId, payloadFingerprint).
 *    - Explicitly classifies and reports storage failures: STORAGE_UNAVAILABLE,
 *      ACCESS_DENIED, QUOTA_EXCEEDED, SET_ITEM_ERROR, READ_ERROR, CORRUPTED_DATA,
 *      READBACK_MISMATCH.
 *    - Maintains an authoritative in-memory lock registry when storage fails so locks
 *      never silently vanish, enters visible safety-degraded mode (reloadSafe: false),
 *      blocks new submissions & fresh nonce creation in the affected scope, and keeps
 *      status checking available.
 *    - Corrupted stored lock data fails CLOSED (locks scope in safety-degraded mode).
 *    - Only authoritative terminal server resolution (CONFIRMED_RECORDED / RECONCILED
 *      or verified 2xx same-nonce completion) may unlock.
 *
 * 2. Canonical Payload Fingerprint Enforcement (Phase 2):
 *    - Deterministically canonicalizes payloads (sorted object keys, nested arrays/objects,
 *      normalized -0, ISO dates, preserves all financially meaningful fields).
 *    - Computes synchronous cryptographic SHA-256 fingerprint (`sha256:<hex>`).
 *    - Fails CLOSED (`PayloadFingerprintError`) on uncomputable/unsupported values
 *      (circular references, NaN, Infinity, invalid Date, Symbol, Function, BigInt).
 *    - Records fingerprint when a transaction becomes UNKNOWN and enforces fingerprint
 *      + nonce identity before every outgoing mutation or recovery retry.
 *    - Blocks modified payloads with unresolved nonces (`PayloadMismatchError`),
 *      blocks fresh-nonce bypasses (`UnknownOutcomeLockBlockedError`), and blocks
 *      retries on `RECOVERY_REQUIRED` transactions.
 */

import { useCallback, useEffect, useState } from 'react';
import type { TransactionStatusResponse, UnknownOutcomeState } from '../services/api';

export const UNKNOWN_LOCK_STORAGE_PREFIX = 'ks_tx_unknown_lock_v1:';

export type LockPersistenceStatus =
  | 'IDLE'
  | 'VERIFIED'
  | 'STORAGE_UNAVAILABLE'
  | 'ACCESS_DENIED'
  | 'QUOTA_EXCEEDED'
  | 'SET_ITEM_ERROR'
  | 'READ_ERROR'
  | 'CORRUPTED_DATA'
  | 'READBACK_MISMATCH';

export interface PersistedUnknownLockRecord {
  version?: number;
  scopeKey?: string;
  outcome: UnknownOutcomeState;
  preservedNonce: string;
  transactionId?: string;
  correlationId?: string;
  payloadFingerprint?: string;
  method?: string;
  path?: string;
  lockedAt: string;
}

export interface LockPersistenceResult {
  ok: boolean;
  persisted: boolean;
  verified: boolean;
  memoryLocked: boolean;
  degraded: boolean;
  reloadSafe: boolean;
  status: LockPersistenceStatus;
  errorMessage?: string;
  record: PersistedUnknownLockRecord | null;
}

export interface NonceLockIdentity {
  nonce: string;
  payloadFingerprint: string;
  method?: string;
  path?: string;
  scopeKey?: string;
  transactionId?: string;
  correlationId?: string;
  transactionState?: UnknownOutcomeState['transactionState'];
  recoveryRequired?: boolean;
  lockedAt: string;
}

interface MemoryScopeLockEntry {
  scopeKey: string;
  record: PersistedUnknownLockRecord | null;
  persistenceStatus: LockPersistenceStatus;
  degraded: boolean;
  reloadSafe: boolean;
  errorMessage?: string;
  corruptedLockActive: boolean;
}

// ---------------------------------------------------------------------------
// Dedicated Fail-Closed Error Classes
// ---------------------------------------------------------------------------

export class PayloadFingerprintError extends Error {
  readonly errorCode = 'PAYLOAD_FINGERPRINT_UNCOMPUTABLE';
  readonly retryable = false;

  constructor(message: string) {
    super(message);
    this.name = 'PayloadFingerprintError';
  }
}

export class PayloadMismatchError extends Error {
  readonly errorCode = 'UNKNOWN_OUTCOME_PAYLOAD_MISMATCH';
  readonly status = 409;
  readonly retryable = false;
  readonly nonce: string;
  readonly scopeKey?: string;
  readonly expectedFingerprint: string;
  readonly actualFingerprint: string;

  constructor(params: {
    nonce: string;
    scopeKey?: string;
    expectedFingerprint: string;
    actualFingerprint: string;
    message?: string;
  }) {
    super(
      params.message ||
        `Payload mismatch blocked for unresolved transaction nonce '${params.nonce}'. Modified transaction payloads cannot reuse an unresolved nonce or bypass an UNKNOWN lock. Check transaction status first.`
    );
    this.name = 'PayloadMismatchError';
    this.nonce = params.nonce;
    this.scopeKey = params.scopeKey;
    this.expectedFingerprint = params.expectedFingerprint;
    this.actualFingerprint = params.actualFingerprint;
  }
}

export type UnknownLockBlockCode =
  | 'UNKNOWN_OUTCOME_LOCK_ACTIVE'
  | 'LOCK_PERSISTENCE_DEGRADED'
  | 'RECOVERY_REQUIRED_LOCKED'
  | 'FRESH_NONCE_BLOCKED';

export class UnknownOutcomeLockBlockedError extends Error {
  readonly errorCode: UnknownLockBlockCode;
  readonly status = 409;
  readonly retryable = false;
  readonly scopeKey?: string;
  readonly nonce?: string;
  readonly persistenceDegraded: boolean;

  constructor(params: {
    errorCode: UnknownLockBlockCode;
    message: string;
    scopeKey?: string;
    nonce?: string;
    persistenceDegraded?: boolean;
  }) {
    super(params.message);
    this.name = 'UnknownOutcomeLockBlockedError';
    this.errorCode = params.errorCode;
    this.scopeKey = params.scopeKey;
    this.nonce = params.nonce;
    this.persistenceDegraded = Boolean(params.persistenceDegraded);
  }
}

// ---------------------------------------------------------------------------
// Pure Synchronous FIPS 180-4 SHA-256 (Browser + Node compatible, zero deps)
// ---------------------------------------------------------------------------

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function utf8ToBytes(input: string): Uint8Array {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(input);
  }
  const bytes: number[] = [];
  for (let i = 0; i < input.length; i++) {
    let cp = input.charCodeAt(i);
    if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < input.length) {
      const next = input.charCodeAt(++i);
      cp = ((cp - 0xd800) << 10) + (next - 0xdc00) + 0x10000;
    }
    if (cp < 0x80) {
      bytes.push(cp);
    } else if (cp < 0x800) {
      bytes.push(0xc0 | (cp >> 6), 0x80 | (cp & 0x3f));
    } else if (cp < 0x10000) {
      bytes.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 0x3f), 0x80 | (cp & 0x3f));
    } else {
      bytes.push(
        0xf0 | (cp >> 18),
        0x80 | ((cp >> 12) & 0x3f),
        0x80 | ((cp >> 6) & 0x3f),
        0x80 | (cp & 0x3f)
      );
    }
  }
  return new Uint8Array(bytes);
}

function sha256Hex(message: string): string {
  const data = utf8ToBytes(message);
  const bitLen = data.length * 8;
  const paddedLen = Math.ceil((data.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLen);
  padded.set(data);
  padded[data.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLen - 8, Math.floor(bitLen / 0x100000000), false);
  view.setUint32(paddedLen - 4, bitLen >>> 0, false);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;

  const w = new Uint32Array(64);
  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i++) {
      w[i] = view.getUint32(offset + i * 4, false);
    }
    for (let i = 16; i < 64; i++) {
      const s0 =
        ((w[i - 15] >>> 7) | (w[i - 15] << 25)) ^
        ((w[i - 15] >>> 18) | (w[i - 15] << 14)) ^
        (w[i - 15] >>> 3);
      const s1 =
        ((w[i - 2] >>> 17) | (w[i - 2] << 15)) ^
        ((w[i - 2] >>> 19) | (w[i - 2] << 13)) ^
        (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((x) => x.toString(16).padStart(8, '0'))
    .join('');
}

// ---------------------------------------------------------------------------
// Deterministic Canonical Payload Serialization & Fingerprinting (Phase 2)
// ---------------------------------------------------------------------------

function canonicalizeValue(value: unknown, seen: Set<object>): string {
  if (value === null) return 'null';
  const t = typeof value;

  if (t === 'boolean') return value ? 'true' : 'false';
  if (t === 'string') return JSON.stringify(value);
  if (t === 'number') {
    const num = value as number;
    if (!Number.isFinite(num)) {
      throw new PayloadFingerprintError(
        `Cannot compute deterministic payload fingerprint: non-finite number (${String(num)}) is not permitted.`
      );
    }
    return Object.is(num, -0) ? '0' : String(num);
  }
  if (t === 'undefined') {
    throw new PayloadFingerprintError(
      'Cannot compute deterministic payload fingerprint: top-level or array undefined value is unsupported.'
    );
  }
  if (t === 'function' || t === 'symbol' || t === 'bigint') {
    throw new PayloadFingerprintError(
      `Cannot compute deterministic payload fingerprint: unsupported payload value type '${t}'.`
    );
  }

  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) {
      throw new PayloadFingerprintError(
        'Cannot compute deterministic payload fingerprint: invalid Date value.'
      );
    }
    return JSON.stringify(value.toISOString());
  }

  if (Array.isArray(value)) {
    if (seen.has(value)) {
      throw new PayloadFingerprintError(
        'Cannot compute deterministic payload fingerprint: circular reference detected in array.'
      );
    }
    seen.add(value);
    try {
      const parts: string[] = [];
      for (let i = 0; i < value.length; i++) {
        const elem = value[i];
        if (elem === undefined) {
          parts.push('null');
        } else {
          parts.push(canonicalizeValue(elem, seen));
        }
      }
      return `[${parts.join(',')}]`;
    } finally {
      seen.delete(value);
    }
  }

  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    if (seen.has(obj)) {
      throw new PayloadFingerprintError(
        'Cannot compute deterministic payload fingerprint: circular reference detected in object.'
      );
    }
    const proto = Object.getPrototypeOf(obj);
    const isPlain = proto === Object.prototype || proto === null;
    if (!isPlain) {
      throw new PayloadFingerprintError(
        `Cannot compute deterministic payload fingerprint: unsupported object class '${obj.constructor?.name || 'Object'}'.`
      );
    }

    seen.add(obj);
    try {
      const keys = Object.keys(obj).sort();
      const entries: string[] = [];
      for (const k of keys) {
        const v = obj[k];
        if (v === undefined) continue;
        entries.push(`${JSON.stringify(k)}:${canonicalizeValue(v, seen)}`);
      }
      return `{${entries.join(',')}}`;
    } finally {
      seen.delete(obj);
    }
  }

  throw new PayloadFingerprintError('Cannot compute deterministic payload fingerprint: unsupported value.');
}

/**
 * Deterministically canonicalizes a payload so identical financial data produces
 * the exact same representation regardless of object key order. Fails closed on
 * circular references, NaN/Infinity, invalid Dates, or unsupported value types.
 */
export function canonicalizePayload(payload: unknown): string {
  if (payload === undefined) {
    return 'null';
  }
  return canonicalizeValue(payload, new Set<object>());
}

/**
 * Computes a deterministic cryptographic SHA-256 fingerprint (`sha256:<hex>`)
 * over the canonicalized transaction payload. Never silently swallows errors —
 * fails closed by throwing `PayloadFingerprintError`.
 */
export function computePayloadFingerprint(payload: unknown): string {
  const canonical = canonicalizePayload(payload);
  return `sha256:${sha256Hex(canonical)}`;
}

/**
 * Computes a canonical payload fingerprint from an HTTP request body (JSON string,
 * URLSearchParams, empty body) plus method/path context. Fails closed on malformed JSON
 * or unsupported non-canonicalizable body types.
 */
export function computeRequestBodyFingerprint(
  rawBody: BodyInit | null | undefined,
  method: string,
  path: string
): string {
  const upperMethod = (method || 'POST').toUpperCase();
  const normalizedPath = String(path || '').trim();

  if (rawBody === null || rawBody === undefined) {
    return computePayloadFingerprint({
      __emptyBody: true,
      __method: upperMethod,
      __path: normalizedPath,
    });
  }

  if (typeof rawBody === 'string') {
    const trimmed = rawBody.trim();
    if (!trimmed) {
      return computePayloadFingerprint({
        __emptyBody: true,
        __method: upperMethod,
        __path: normalizedPath,
      });
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch (err: unknown) {
      throw new PayloadFingerprintError(
        `Cannot verify payload identity: request body is not valid JSON (${
          err instanceof Error ? err.message : String(err)
        }).`
      );
    }
    return computePayloadFingerprint(parsed);
  }

  if (typeof URLSearchParams !== 'undefined' && rawBody instanceof URLSearchParams) {
    const entries = Array.from(rawBody.entries()).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return computePayloadFingerprint({ __urlSearchParams: entries });
  }

  throw new PayloadFingerprintError(
    'Cannot compute deterministic payload fingerprint for unsupported request body type.'
  );
}

// ---------------------------------------------------------------------------
// Authoritative In-Memory Lock & Nonce Identity Registries
// ---------------------------------------------------------------------------

const memoryScopeLocks = new Map<string, MemoryScopeLockEntry>();
const nonceIdentityRegistry = new Map<string, NonceLockIdentity>();
const verifiedRetryAuthorizedNonces = new Map<
  string,
  { payloadFingerprint?: string; authorizedAt: number }
>();
const verifiedTerminalResolvedNonces = new Set<string>();

function classifyStorageError(err: unknown, phase: 'access' | 'set' | 'get' | 'remove'): {
  status: LockPersistenceStatus;
  message: string;
} {
  const name = err instanceof Error ? err.name : '';
  const msg = err instanceof Error ? err.message : String(err ?? 'Unknown storage error');
  const lower = `${name} ${msg}`.toLowerCase();

  if (
    name === 'QuotaExceededError' ||
    name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
    lower.includes('quota')
  ) {
    return {
      status: 'QUOTA_EXCEEDED',
      message: `Browser sessionStorage quota exceeded while persisting UNKNOWN lock (${msg}).`,
    };
  }
  if (
    name === 'SecurityError' ||
    lower.includes('access denied') ||
    lower.includes('permission denied') ||
    lower.includes('securityerror') ||
    lower.includes('denied')
  ) {
    return {
      status: 'ACCESS_DENIED',
      message: `Browser sessionStorage access denied (${msg}).`,
    };
  }
  if (phase === 'set') {
    return {
      status: 'SET_ITEM_ERROR',
      message: `sessionStorage.setItem failed (${msg}).`,
    };
  }
  if (phase === 'get') {
    return {
      status: 'READ_ERROR',
      message: `sessionStorage.getItem failed (${msg}).`,
    };
  }
  return {
    status: 'ACCESS_DENIED',
    message: `sessionStorage operation failed (${msg}).`,
  };
}

function acquireSessionStorage(): {
  storage: Storage | null;
  status: LockPersistenceStatus;
  errorMessage?: string;
} {
  try {
    if (typeof window === 'undefined') {
      return {
        storage: null,
        status: 'STORAGE_UNAVAILABLE',
        errorMessage: 'window is unavailable; sessionStorage cannot persist lock across reloads.',
      };
    }
    const store = window.sessionStorage;
    if (!store || typeof store.getItem !== 'function' || typeof store.setItem !== 'function') {
      return {
        storage: null,
        status: 'STORAGE_UNAVAILABLE',
        errorMessage: 'window.sessionStorage is unavailable in this browser context.',
      };
    }
    return { storage: store, status: 'VERIFIED' };
  } catch (err: unknown) {
    const classified = classifyStorageError(err, 'access');
    return {
      storage: null,
      status: classified.status,
      errorMessage: classified.message,
    };
  }
}

function isValidPersistedRecordShape(
  parsed: unknown,
  expectedScopeKey: string
): parsed is PersistedUnknownLockRecord {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return false;
  const rec = parsed as Record<string, unknown>;
  if (typeof rec.preservedNonce !== 'string' || !rec.preservedNonce.trim()) return false;
  if (!rec.outcome || typeof rec.outcome !== 'object' || Array.isArray(rec.outcome)) return false;
  const outcome = rec.outcome as Record<string, unknown>;
  if (typeof outcome.nonce !== 'string' || !outcome.nonce.trim()) return false;
  if (outcome.nonce !== rec.preservedNonce) return false;
  if (rec.scopeKey !== undefined && rec.scopeKey !== expectedScopeKey) return false;
  if (typeof rec.lockedAt !== 'string' || !rec.lockedAt.trim()) return false;
  return true;
}

function buildDegradedCorruptedOutcome(
  scopeKey: string,
  status: LockPersistenceStatus,
  errorMessage: string
): UnknownOutcomeState {
  return {
    nonce: '',
    scopeKey,
    transactionState: 'RECOVERY_REQUIRED',
    recoveryRequired: true,
    persistenceDegraded: true,
    persistenceStatus: status,
    persistenceFailureReason: errorMessage,
    reloadSafe: false,
    actionLabel: 'Corrupted / Unreadable Transaction Lock',
    message:
      'Safety-degraded lock active: stored UNKNOWN transaction lock could not be read or verified. All new submissions in this screen are blocked to prevent duplicate transactions. Inspect recent transactions or contact Owner/Admin before proceeding.',
  };
}

function enrichOutcomeWithLockMetadata(
  outcome: UnknownOutcomeState,
  meta: {
    scopeKey?: string;
    payloadFingerprint?: string;
    persistenceStatus?: LockPersistenceStatus;
    persistenceDegraded?: boolean;
    persistenceFailureReason?: string;
    reloadSafe?: boolean;
  }
): UnknownOutcomeState {
  return {
    ...outcome,
    scopeKey: meta.scopeKey ?? outcome.scopeKey,
    payloadFingerprint: meta.payloadFingerprint ?? outcome.payloadFingerprint,
    persistenceStatus: meta.persistenceStatus ?? outcome.persistenceStatus,
    persistenceDegraded:
      meta.persistenceDegraded !== undefined
        ? meta.persistenceDegraded
        : outcome.persistenceDegraded,
    persistenceFailureReason:
      meta.persistenceFailureReason !== undefined
        ? meta.persistenceFailureReason
        : outcome.persistenceFailureReason,
    reloadSafe: meta.reloadSafe !== undefined ? meta.reloadSafe : outcome.reloadSafe,
  };
}

// ---------------------------------------------------------------------------
// Public Helpers & Lock State Queries
// ---------------------------------------------------------------------------

export function isOutcomeLocked(outcome: UnknownOutcomeState | null | undefined): boolean {
  if (!outcome) return false;
  return Boolean(outcome.nonce || outcome.persistenceDegraded || outcome.recoveryRequired);
}

/**
 * Guard helper for form field onChange handlers that would otherwise reset a draft nonce.
 * While an UNKNOWN / RECOVERY_REQUIRED / persistence-degraded outcome is active, payload
 * edits MUST NOT clear or rotate the preserved nonce.
 */
export function shouldBlockDraftNonceReset(outcome: UnknownOutcomeState | null | undefined): boolean {
  return isOutcomeLocked(outcome);
}

export function isScopeLocked(scopeKey: string): boolean {
  if (!scopeKey) return false;
  const mem = memoryScopeLocks.get(scopeKey);
  if (mem && (mem.record || mem.corruptedLockActive)) return true;
  const inspected = inspectPersistedUnknownOutcome(scopeKey);
  return Boolean(inspected.record || inspected.degraded);
}

export function getMemoryScopeLock(scopeKey: string): MemoryScopeLockEntry | null {
  return memoryScopeLocks.get(scopeKey) || null;
}

export function getRegisteredNonceIdentity(nonce: string): NonceLockIdentity | null {
  if (!nonce) return null;
  return nonceIdentityRegistry.get(nonce) || null;
}

/**
 * Registers an unresolved UNKNOWN / RECOVERY_REQUIRED transaction identity at the
 * transport layer (`apiRequest` / `apiFetch`) so canonical payload fingerprinting is
 * strictly enforced even before a view calls `persistUnknownOutcome`.
 */
export function registerUnknownTransactionIdentity(identity: {
  nonce: string;
  payloadFingerprint: string;
  method?: string;
  path?: string;
  scopeKey?: string;
  transactionId?: string;
  correlationId?: string;
  transactionState?: UnknownOutcomeState['transactionState'];
  recoveryRequired?: boolean;
}): NonceLockIdentity {
  const existing = nonceIdentityRegistry.get(identity.nonce);
  const entry: NonceLockIdentity = {
    nonce: identity.nonce,
    payloadFingerprint: identity.payloadFingerprint || existing?.payloadFingerprint || '',
    method: identity.method ?? existing?.method,
    path: identity.path ?? existing?.path,
    scopeKey: identity.scopeKey ?? existing?.scopeKey,
    transactionId: identity.transactionId ?? existing?.transactionId,
    correlationId: identity.correlationId ?? existing?.correlationId,
    transactionState: identity.transactionState ?? existing?.transactionState ?? 'UNKNOWN',
    recoveryRequired: Boolean(
      identity.recoveryRequired ||
        identity.transactionState === 'RECOVERY_REQUIRED' ||
        existing?.recoveryRequired
    ),
    lockedAt: existing?.lockedAt || new Date().toISOString(),
  };
  nonceIdentityRegistry.set(identity.nonce, entry);
  verifiedTerminalResolvedNonces.delete(identity.nonce);
  if (entry.recoveryRequired) {
    verifiedRetryAuthorizedNonces.delete(identity.nonce);
  }
  return entry;
}

/**
 * Persists an UNKNOWN / RECOVERY_REQUIRED transaction lock to sessionStorage AND verifies
 * immediate read-back integrity. If storage is unavailable, denies access, throws quota/write
 * errors, or fails readback verification:
 * - The lock is ALWAYS maintained in memory (`memoryLocked: true`).
 * - Returns an explicit `LockPersistenceResult` with `degraded: true`, `reloadSafe: false`,
 *   exact `status`, and `errorMessage` (never silently pretending persistence succeeded).
 */
export function persistUnknownOutcome(
  scopeKey: string,
  outcome: UnknownOutcomeState,
  payloadOrFingerprint?: unknown
): LockPersistenceResult {
  if (!scopeKey || !outcome?.nonce) {
    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: false,
      degraded: true,
      reloadSafe: false,
      status: 'SET_ITEM_ERROR',
      errorMessage: 'Cannot persist UNKNOWN lock without valid scopeKey and nonce.',
      record: null,
    };
  }

  let resolvedFingerprint: string | undefined = outcome.payloadFingerprint;
  if (typeof payloadOrFingerprint === 'string' && payloadOrFingerprint.startsWith('sha256:')) {
    resolvedFingerprint = payloadOrFingerprint;
  } else if (payloadOrFingerprint !== undefined) {
    // Throws PayloadFingerprintError fail-closed if uncomputable!
    resolvedFingerprint = computePayloadFingerprint(payloadOrFingerprint);
  } else if (!resolvedFingerprint) {
    const existingReg = nonceIdentityRegistry.get(outcome.nonce);
    if (existingReg?.payloadFingerprint) {
      resolvedFingerprint = existingReg.payloadFingerprint;
    }
  }

  const baseRecord: PersistedUnknownLockRecord = {
    version: 2,
    scopeKey,
    outcome: {
      ...outcome,
      scopeKey,
      payloadFingerprint: resolvedFingerprint,
    },
    preservedNonce: outcome.nonce,
    transactionId: outcome.transactionId,
    correlationId: outcome.correlationId,
    payloadFingerprint: resolvedFingerprint,
    lockedAt: new Date().toISOString(),
  };

  // Register nonce identity in memory FIRST so enforcement is active even if storage crashes
  if (resolvedFingerprint) {
    registerUnknownTransactionIdentity({
      nonce: outcome.nonce,
      payloadFingerprint: resolvedFingerprint,
      scopeKey,
      transactionId: outcome.transactionId,
      correlationId: outcome.correlationId,
      transactionState: outcome.transactionState,
      recoveryRequired: outcome.recoveryRequired,
    });
  } else {
    const prev = nonceIdentityRegistry.get(outcome.nonce);
    nonceIdentityRegistry.set(outcome.nonce, {
      nonce: outcome.nonce,
      payloadFingerprint: prev?.payloadFingerprint || '',
      scopeKey,
      transactionId: outcome.transactionId ?? prev?.transactionId,
      correlationId: outcome.correlationId ?? prev?.correlationId,
      transactionState: outcome.transactionState ?? prev?.transactionState ?? 'UNKNOWN',
      recoveryRequired: Boolean(outcome.recoveryRequired || prev?.recoveryRequired),
      lockedAt: prev?.lockedAt || baseRecord.lockedAt,
    });
  }

  const storeCheck = acquireSessionStorage();
  if (!storeCheck.storage) {
    const degradedRecord: PersistedUnknownLockRecord = {
      ...baseRecord,
      outcome: enrichOutcomeWithLockMetadata(baseRecord.outcome, {
        scopeKey,
        payloadFingerprint: resolvedFingerprint,
        persistenceStatus: storeCheck.status,
        persistenceDegraded: true,
        persistenceFailureReason: storeCheck.errorMessage,
        reloadSafe: false,
      }),
    };
    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: degradedRecord,
      persistenceStatus: storeCheck.status,
      degraded: true,
      reloadSafe: false,
      errorMessage: storeCheck.errorMessage,
      corruptedLockActive: false,
    });
    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: true,
      degraded: true,
      reloadSafe: false,
      status: storeCheck.status,
      errorMessage: storeCheck.errorMessage,
      record: degradedRecord,
    };
  }

  const storageKey = `${UNKNOWN_LOCK_STORAGE_PREFIX}${scopeKey}`;
  const serialized = JSON.stringify(baseRecord);

  // Step 1: Write to sessionStorage
  try {
    storeCheck.storage.setItem(storageKey, serialized);
  } catch (err: unknown) {
    const classified = classifyStorageError(err, 'set');
    const degradedRecord: PersistedUnknownLockRecord = {
      ...baseRecord,
      outcome: enrichOutcomeWithLockMetadata(baseRecord.outcome, {
        scopeKey,
        payloadFingerprint: resolvedFingerprint,
        persistenceStatus: classified.status,
        persistenceDegraded: true,
        persistenceFailureReason: classified.message,
        reloadSafe: false,
      }),
    };
    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: degradedRecord,
      persistenceStatus: classified.status,
      degraded: true,
      reloadSafe: false,
      errorMessage: classified.message,
      corruptedLockActive: false,
    });
    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: true,
      degraded: true,
      reloadSafe: false,
      status: classified.status,
      errorMessage: classified.message,
      record: degradedRecord,
    };
  }

  // Step 2: Immediate readback verification
  let readBackRaw: string | null = null;
  try {
    readBackRaw = storeCheck.storage.getItem(storageKey);
  } catch (err: unknown) {
    const classified = classifyStorageError(err, 'get');
    const degradedRecord: PersistedUnknownLockRecord = {
      ...baseRecord,
      outcome: enrichOutcomeWithLockMetadata(baseRecord.outcome, {
        scopeKey,
        payloadFingerprint: resolvedFingerprint,
        persistenceStatus: classified.status,
        persistenceDegraded: true,
        persistenceFailureReason: `Lock write could not be verified via readback: ${classified.message}`,
        reloadSafe: false,
      }),
    };
    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: degradedRecord,
      persistenceStatus: classified.status,
      degraded: true,
      reloadSafe: false,
      errorMessage: degradedRecord.outcome.persistenceFailureReason,
      corruptedLockActive: false,
    });
    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: true,
      degraded: true,
      reloadSafe: false,
      status: classified.status,
      errorMessage: degradedRecord.outcome.persistenceFailureReason,
      record: degradedRecord,
    };
  }

  let verified = false;
  let mismatchDetail = '';
  if (!readBackRaw) {
    mismatchDetail = 'Immediate sessionStorage readback returned empty/null after setItem.';
  } else {
    try {
      const readBackParsed = JSON.parse(readBackRaw);
      if (
        isValidPersistedRecordShape(readBackParsed, scopeKey) &&
        readBackParsed.preservedNonce === baseRecord.preservedNonce &&
        readBackParsed.outcome.nonce === baseRecord.outcome.nonce &&
        (readBackParsed.payloadFingerprint ?? undefined) === (resolvedFingerprint ?? undefined) &&
        (readBackParsed.transactionId ?? undefined) === (baseRecord.transactionId ?? undefined)
      ) {
        verified = true;
      } else {
        mismatchDetail =
          'Immediate sessionStorage readback did not match written nonce, scope, transaction ID, or payload fingerprint.';
      }
    } catch (err: unknown) {
      mismatchDetail = `Immediate sessionStorage readback returned unparseable data (${
        err instanceof Error ? err.message : String(err)
      }).`;
    }
  }

  if (!verified) {
    const degradedRecord: PersistedUnknownLockRecord = {
      ...baseRecord,
      outcome: enrichOutcomeWithLockMetadata(baseRecord.outcome, {
        scopeKey,
        payloadFingerprint: resolvedFingerprint,
        persistenceStatus: 'READBACK_MISMATCH',
        persistenceDegraded: true,
        persistenceFailureReason: mismatchDetail,
        reloadSafe: false,
      }),
    };
    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: degradedRecord,
      persistenceStatus: 'READBACK_MISMATCH',
      degraded: true,
      reloadSafe: false,
      errorMessage: mismatchDetail,
      corruptedLockActive: false,
    });
    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: true,
      degraded: true,
      reloadSafe: false,
      status: 'READBACK_MISMATCH',
      errorMessage: mismatchDetail,
      record: degradedRecord,
    };
  }

  const verifiedRecord: PersistedUnknownLockRecord = {
    ...baseRecord,
    outcome: enrichOutcomeWithLockMetadata(baseRecord.outcome, {
      scopeKey,
      payloadFingerprint: resolvedFingerprint,
      persistenceStatus: 'VERIFIED',
      persistenceDegraded: false,
      persistenceFailureReason: undefined,
      reloadSafe: true,
    }),
  };
  memoryScopeLocks.set(scopeKey, {
    scopeKey,
    record: verifiedRecord,
    persistenceStatus: 'VERIFIED',
    degraded: false,
    reloadSafe: true,
    corruptedLockActive: false,
  });

  return {
    ok: true,
    persisted: true,
    verified: true,
    memoryLocked: true,
    degraded: false,
    reloadSafe: true,
    status: 'VERIFIED',
    record: verifiedRecord,
  };
}

/**
 * Inspects persisted UNKNOWN lock state with explicit error classification.
 * Never swallows read exceptions or corrupted JSON silently:
 * - Corrupted stored data or storage read exceptions fail CLOSED (`degraded: true`,
 *   `memoryLocked: true`) so the affected scope remains locked.
 * - If an in-memory lock exists when storage is unavailable/broken, returns that
 *   authoritative memory lock with `degraded: true, reloadSafe: false`.
 */
export function inspectPersistedUnknownOutcome(scopeKey: string): LockPersistenceResult {
  if (!scopeKey) {
    return {
      ok: true,
      persisted: false,
      verified: false,
      memoryLocked: false,
      degraded: false,
      reloadSafe: true,
      status: 'IDLE',
      record: null,
    };
  }

  const memEntry = memoryScopeLocks.get(scopeKey) || null;
  const storeCheck = acquireSessionStorage();

  if (!storeCheck.storage) {
    if (memEntry && (memEntry.record || memEntry.corruptedLockActive)) {
      return {
        ok: false,
        persisted: false,
        verified: false,
        memoryLocked: true,
        degraded: true,
        reloadSafe: false,
        status: storeCheck.status,
        errorMessage: storeCheck.errorMessage,
        record: memEntry.record,
      };
    }
    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: false,
      degraded: storeCheck.status === 'ACCESS_DENIED',
      reloadSafe: false,
      status: storeCheck.status,
      errorMessage: storeCheck.errorMessage,
      record: null,
    };
  }

  const storageKey = `${UNKNOWN_LOCK_STORAGE_PREFIX}${scopeKey}`;
  let raw: string | null = null;
  try {
    raw = storeCheck.storage.getItem(storageKey);
  } catch (err: unknown) {
    const classified = classifyStorageError(err, 'get');
    const fallbackRecord = memEntry?.record
      ? {
          ...memEntry.record,
          outcome: enrichOutcomeWithLockMetadata(memEntry.record.outcome, {
            scopeKey,
            persistenceStatus: classified.status,
            persistenceDegraded: true,
            persistenceFailureReason: classified.message,
            reloadSafe: false,
          }),
        }
      : null;

    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: fallbackRecord,
      persistenceStatus: classified.status,
      degraded: true,
      reloadSafe: false,
      errorMessage: classified.message,
      corruptedLockActive: !fallbackRecord,
    });

    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: true,
      degraded: true,
      reloadSafe: false,
      status: classified.status,
      errorMessage: classified.message,
      record: fallbackRecord,
    };
  }

  if (raw === null) {
    // Storage has no entry. If an active in-memory lock exists (e.g., setItem failed earlier),
    // NEVER drop the in-memory lock!
    if (memEntry && memEntry.record) {
      return {
        ok: false,
        persisted: false,
        verified: false,
        memoryLocked: true,
        degraded: true,
        reloadSafe: false,
        status: memEntry.persistenceStatus === 'VERIFIED' ? 'READBACK_MISMATCH' : memEntry.persistenceStatus,
        errorMessage:
          memEntry.errorMessage ||
          'UNKNOWN lock exists in memory but is missing from sessionStorage; reload safety is degraded.',
        record: {
          ...memEntry.record,
          outcome: enrichOutcomeWithLockMetadata(memEntry.record.outcome, {
            scopeKey,
            persistenceStatus:
              memEntry.persistenceStatus === 'VERIFIED'
                ? 'READBACK_MISMATCH'
                : memEntry.persistenceStatus,
            persistenceDegraded: true,
            persistenceFailureReason:
              memEntry.errorMessage ||
              'UNKNOWN lock exists in memory but is missing from sessionStorage; reload safety is degraded.',
            reloadSafe: false,
          }),
        },
      };
    }
    return {
      ok: true,
      persisted: false,
      verified: true,
      memoryLocked: false,
      degraded: false,
      reloadSafe: true,
      status: 'IDLE',
      record: null,
    };
  }

  try {
    const parsed = JSON.parse(raw);
    if (!isValidPersistedRecordShape(parsed, scopeKey)) {
      throw new Error('Stored UNKNOWN lock record failed structural/nonce validation.');
    }

    // If an authoritative in-memory lock already exists for this scope, NEVER let stale
    // or tampered sessionStorage overwrite it with a different nonce or fingerprint!
    if (
      memEntry?.record &&
      (parsed.preservedNonce !== memEntry.record.preservedNonce ||
        (memEntry.record.payloadFingerprint &&
          parsed.payloadFingerprint !== memEntry.record.payloadFingerprint))
    ) {
      const mismatchMsg = `sessionStorage lock for '${scopeKey}' diverged from authoritative in-memory lock (memory nonce '${memEntry.record.preservedNonce}' vs storage nonce '${parsed.preservedNonce}'). Preserving in-memory lock in safety-degraded mode.`;
      const preservedRecord: PersistedUnknownLockRecord = {
        ...memEntry.record,
        outcome: enrichOutcomeWithLockMetadata(memEntry.record.outcome, {
          scopeKey,
          persistenceStatus: 'READBACK_MISMATCH',
          persistenceDegraded: true,
          persistenceFailureReason: mismatchMsg,
          reloadSafe: false,
        }),
      };
      memoryScopeLocks.set(scopeKey, {
        scopeKey,
        record: preservedRecord,
        persistenceStatus: 'READBACK_MISMATCH',
        degraded: true,
        reloadSafe: false,
        errorMessage: mismatchMsg,
        corruptedLockActive: false,
      });
      return {
        ok: false,
        persisted: false,
        verified: false,
        memoryLocked: true,
        degraded: true,
        reloadSafe: false,
        status: 'READBACK_MISMATCH',
        errorMessage: mismatchMsg,
        record: preservedRecord,
      };
    }

    const hydratedRecord: PersistedUnknownLockRecord = {
      ...parsed,
      scopeKey,
      outcome: enrichOutcomeWithLockMetadata(parsed.outcome, {
        scopeKey,
        payloadFingerprint: parsed.payloadFingerprint ?? parsed.outcome.payloadFingerprint,
        persistenceStatus: 'VERIFIED',
        persistenceDegraded: false,
        persistenceFailureReason: undefined,
        reloadSafe: true,
      }),
    };

    // Hydrate in-memory registries so remount/reload enforces fingerprint + nonce immediately!
    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: hydratedRecord,
      persistenceStatus: 'VERIFIED',
      degraded: false,
      reloadSafe: true,
      corruptedLockActive: false,
    });
    registerUnknownTransactionIdentity({
      nonce: hydratedRecord.preservedNonce,
      payloadFingerprint: hydratedRecord.payloadFingerprint || '',
      scopeKey,
      transactionId: hydratedRecord.transactionId ?? hydratedRecord.outcome.transactionId,
      correlationId: hydratedRecord.correlationId ?? hydratedRecord.outcome.correlationId,
      transactionState: hydratedRecord.outcome.transactionState,
      recoveryRequired: hydratedRecord.outcome.recoveryRequired,
    });

    return {
      ok: true,
      persisted: true,
      verified: true,
      memoryLocked: true,
      degraded: false,
      reloadSafe: true,
      status: 'VERIFIED',
      record: hydratedRecord,
    };
  } catch (err: unknown) {
    const errMsg = `Corrupted UNKNOWN transaction lock detected in sessionStorage for '${scopeKey}': ${
      err instanceof Error ? err.message : String(err)
    }`;
    const fallbackRecord = memEntry?.record
      ? {
          ...memEntry.record,
          outcome: enrichOutcomeWithLockMetadata(memEntry.record.outcome, {
            scopeKey,
            persistenceStatus: 'CORRUPTED_DATA',
            persistenceDegraded: true,
            persistenceFailureReason: errMsg,
            reloadSafe: false,
          }),
        }
      : null;

    memoryScopeLocks.set(scopeKey, {
      scopeKey,
      record: fallbackRecord,
      persistenceStatus: 'CORRUPTED_DATA',
      degraded: true,
      reloadSafe: false,
      errorMessage: errMsg,
      corruptedLockActive: !fallbackRecord,
    });

    return {
      ok: false,
      persisted: false,
      verified: false,
      memoryLocked: true,
      degraded: true,
      reloadSafe: false,
      status: 'CORRUPTED_DATA',
      errorMessage: errMsg,
      record: fallbackRecord,
    };
  }
}

/**
 * Backward-compatible loader returning the active lock record (from verified sessionStorage
 * or authoritative in-memory fallback), or null when no valid lock record exists.
 * For full error/corruption status, use `inspectPersistedUnknownOutcome(scopeKey)`.
 */
export function loadPersistedUnknownOutcome(scopeKey: string): PersistedUnknownLockRecord | null {
  const inspected = inspectPersistedUnknownOutcome(scopeKey);
  return inspected.record;
}

/**
 * Records an authoritative response from `GET /api/v2/transactions/status/{nonce}`.
 * - `CONFIRMED_RECORDED` / `RECONCILED`: marks transaction terminally resolved so verified unlock is permitted.
 * - `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` (`safe_to_retry_same_nonce === true`): authorizes same-nonce
 *   retry strictly for the matching canonical payload fingerprint (blocked if RECOVERY_REQUIRED).
 * - `RECOVERY_REQUIRED`: permanently locks retry and upgrades active lock to RECOVERY_REQUIRED.
 * - `IN_PROGRESS` / `UNKNOWN_STORAGE_UNAVAILABLE`: keeps lock active and does NOT authorize retry or unlock.
 */
export function recordAuthoritativeStatusCheckResult(
  nonce: string,
  statusResponse: Pick<
    TransactionStatusResponse,
    'status' | 'safe_to_retry_same_nonce' | 'transaction_state'
  >
): void {
  if (!nonce || !statusResponse) return;
  const status = statusResponse.status;
  const reg = nonceIdentityRegistry.get(nonce);

  if (status === 'CONFIRMED_RECORDED' || status === 'RECONCILED') {
    verifiedTerminalResolvedNonces.add(nonce);
    verifiedRetryAuthorizedNonces.delete(nonce);
    return;
  }

  if (status === 'RECOVERY_REQUIRED' || statusResponse.transaction_state === 'RECOVERY_REQUIRED') {
    verifiedRetryAuthorizedNonces.delete(nonce);
    verifiedTerminalResolvedNonces.delete(nonce);
    if (reg) {
      reg.recoveryRequired = true;
      reg.transactionState = 'RECOVERY_REQUIRED';
    }
    for (const [scopeKey, entry] of memoryScopeLocks.entries()) {
      if (entry.record && entry.record.preservedNonce === nonce) {
        entry.record.outcome = {
          ...entry.record.outcome,
          recoveryRequired: true,
          transactionState: 'RECOVERY_REQUIRED',
        };
        persistUnknownOutcome(scopeKey, entry.record.outcome, entry.record.payloadFingerprint);
      }
    }
    return;
  }

  if (
    status === 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE' &&
    statusResponse.safe_to_retry_same_nonce === true
  ) {
    if (reg?.recoveryRequired) {
      verifiedRetryAuthorizedNonces.delete(nonce);
      return;
    }
    verifiedRetryAuthorizedNonces.set(nonce, {
      payloadFingerprint: reg?.payloadFingerprint,
      authorizedAt: Date.now(),
    });
    return;
  }

  // IN_PROGRESS or UNKNOWN_STORAGE_UNAVAILABLE: keep locked, do not authorize retry or unlock
  verifiedRetryAuthorizedNonces.delete(nonce);
}

/**
 * Checks whether a nonce has received authoritative terminal resolution
 * (`CONFIRMED_RECORDED` or `RECONCILED`) from the backend.
 */
export function isNonceTerminallyResolved(nonce: string): boolean {
  return Boolean(nonce && verifiedTerminalResolvedNonces.has(nonce));
}

/**
 * Marks a transaction terminally resolved after a verified HTTP 2xx server confirmation.
 */
export function markTransactionTerminallyResolved(nonce?: string, scopeKey?: string): void {
  if (nonce) {
    verifiedTerminalResolvedNonces.add(nonce);
    verifiedRetryAuthorizedNonces.delete(nonce);
    const reg = nonceIdentityRegistry.get(nonce);
    const linkedScope = scopeKey || reg?.scopeKey;
    nonceIdentityRegistry.delete(nonce);
    if (linkedScope) {
      const mem = memoryScopeLocks.get(linkedScope);
      if (mem?.record?.preservedNonce === nonce) {
        clearPersistedUnknownOutcome(linkedScope);
      }
    }
  }
}

/**
 * Clears a scope's lock ONLY after verified terminal resolution.
 * Rejects clearing if the provided resolution status is not `CONFIRMED_RECORDED`,
 * `RECONCILED`, or `RETRY_SUCCEEDED`.
 */
export function resolveAndClearUnknownOutcome(
  scopeKey: string,
  resolution: {
    status: TransactionStatusResponse['status'] | 'RETRY_SUCCEEDED';
    nonce?: string;
  }
): { cleared: boolean; storageCleared: boolean; reason?: string } {
  const isTerminal =
    resolution.status === 'CONFIRMED_RECORDED' ||
    resolution.status === 'RECONCILED' ||
    resolution.status === 'RETRY_SUCCEEDED';

  if (!isTerminal) {
    return {
      cleared: false,
      storageCleared: false,
      reason: `Cannot clear UNKNOWN lock for non-terminal status '${resolution.status}'.`,
    };
  }

  const res = clearPersistedUnknownOutcome(scopeKey);
  if (resolution.nonce) {
    verifiedTerminalResolvedNonces.add(resolution.nonce);
    verifiedRetryAuthorizedNonces.delete(resolution.nonce);
    nonceIdentityRegistry.delete(resolution.nonce);
  }
  return { cleared: true, storageCleared: res.storageCleared, reason: res.errorMessage };
}

/**
 * Clears memory and sessionStorage lock entries for `scopeKey` after verified resolution.
 * Returns explicit status instead of silently swallowing removeItem errors.
 */
export function clearPersistedUnknownOutcome(scopeKey: string): {
  memoryCleared: boolean;
  storageCleared: boolean;
  errorMessage?: string;
} {
  if (!scopeKey) return { memoryCleared: false, storageCleared: false };
  const existing = memoryScopeLocks.get(scopeKey);
  if (existing?.record?.preservedNonce) {
    nonceIdentityRegistry.delete(existing.record.preservedNonce);
    verifiedRetryAuthorizedNonces.delete(existing.record.preservedNonce);
  }
  memoryScopeLocks.delete(scopeKey);

  const storeCheck = acquireSessionStorage();
  if (!storeCheck.storage) {
    return {
      memoryCleared: true,
      storageCleared: false,
      errorMessage: storeCheck.errorMessage,
    };
  }
  try {
    storeCheck.storage.removeItem(`${UNKNOWN_LOCK_STORAGE_PREFIX}${scopeKey}`);
    return { memoryCleared: true, storageCleared: true };
  } catch (err: unknown) {
    const classified = classifyStorageError(err, 'remove');
    return {
      memoryCleared: true,
      storageCleared: false,
      errorMessage: classified.message,
    };
  }
}

/**
 * Blocks fresh nonce generation whenever `scopeKey` holds an active UNKNOWN,
 * RECOVERY_REQUIRED, or corrupted/degraded lock.
 */
export function assertFreshNonceAllowed(scopeKey: string): void {
  if (!scopeKey) return;
  const inspected = inspectPersistedUnknownOutcome(scopeKey);
  if (inspected.record) {
    throw new UnknownOutcomeLockBlockedError({
      errorCode: 'FRESH_NONCE_BLOCKED',
      scopeKey,
      nonce: inspected.record.preservedNonce,
      persistenceDegraded: inspected.degraded,
      message: `Cannot generate a fresh nonce in '${scopeKey}' while unresolved transaction nonce '${inspected.record.preservedNonce}' is locked. Verify transaction status first.`,
    });
  }
  if (inspected.degraded && inspected.memoryLocked) {
    throw new UnknownOutcomeLockBlockedError({
      errorCode: 'LOCK_PERSISTENCE_DEGRADED',
      scopeKey,
      persistenceDegraded: true,
      message: `Cannot generate a fresh nonce in '${scopeKey}': transaction lock storage is degraded/corrupted (${inspected.status}).`,
    });
  }
}

/**
 * Enforces BOTH scope lock safety AND canonical payload fingerprint identity
 * before any mutation or recovery retry executes.
 *
 * Fails closed when:
 * 1. Payload fingerprint cannot be computed (throws `PayloadFingerprintError`).
 * 2. Affected `scopeKey` has a corrupted/unreadable lock (throws `UnknownOutcomeLockBlockedError`).
 * 3. Affected `scopeKey` has an active unresolved lock and caller supplies a DIFFERENT nonce
 *    (blocks fresh-nonce bypass — throws `UnknownOutcomeLockBlockedError`).
 * 4. Locked transaction is in `RECOVERY_REQUIRED` state (throws `UnknownOutcomeLockBlockedError`).
 * 5. Caller reuses an unresolved `nonce` with a MODIFIED canonical payload fingerprint
 *    (throws `PayloadMismatchError`).
 * 6. Caller attempts a retry on a locked `scopeKey` without authoritative `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE`
 *    verification when `requireVerifiedRetry` is true (throws `UnknownOutcomeLockBlockedError`).
 */
export function verifyPayloadAgainstActiveLock(params: {
  scopeKey?: string;
  nonce?: string;
  payload?: unknown;
  rawBody?: BodyInit | null;
  method?: string;
  path?: string;
  requireVerifiedRetry?: boolean;
}): { payloadFingerprint: string } {
  // Always compute canonical fingerprint first — fail closed if uncomputable!
  const payloadFingerprint =
    params.payload !== undefined
      ? computePayloadFingerprint(params.payload)
      : computeRequestBodyFingerprint(params.rawBody, params.method || 'POST', params.path || '');

  const nonce = (params.nonce || '').trim();
  const scopeKey = (params.scopeKey || '').trim();

  // 1. Check scope-level lock (including corrupted storage or memory-only degraded locks)
  if (scopeKey) {
    const inspected = inspectPersistedUnknownOutcome(scopeKey);
    if (inspected.degraded && inspected.memoryLocked && !inspected.record) {
      throw new UnknownOutcomeLockBlockedError({
        errorCode: 'LOCK_PERSISTENCE_DEGRADED',
        scopeKey,
        persistenceDegraded: true,
        message:
          inspected.errorMessage ||
          `Submission blocked in '${scopeKey}': UNKNOWN lock storage is corrupted or unreadable.`,
      });
    }

    if (inspected.record) {
      const lockedNonce = inspected.record.preservedNonce;
      if (inspected.record.outcome.recoveryRequired || inspected.record.outcome.transactionState === 'RECOVERY_REQUIRED') {
        throw new UnknownOutcomeLockBlockedError({
          errorCode: 'RECOVERY_REQUIRED_LOCKED',
          scopeKey,
          nonce: lockedNonce,
          persistenceDegraded: inspected.degraded,
          message: `Submission blocked in '${scopeKey}': transaction '${lockedNonce}' requires administrator reconciliation (RECOVERY_REQUIRED).`,
        });
      }

      if (!nonce || nonce !== lockedNonce) {
        throw new UnknownOutcomeLockBlockedError({
          errorCode: 'UNKNOWN_OUTCOME_LOCK_ACTIVE',
          scopeKey,
          nonce: lockedNonce,
          persistenceDegraded: inspected.degraded,
          message: `New transaction blocked in '${scopeKey}': unresolved transaction nonce '${lockedNonce}' is locked. Do not create a fresh nonce to bypass an UNKNOWN outcome.`,
        });
      }

      const expectedFp =
        inspected.record.payloadFingerprint ||
        nonceIdentityRegistry.get(lockedNonce)?.payloadFingerprint;
      if (expectedFp && expectedFp !== payloadFingerprint) {
        throw new PayloadMismatchError({
          nonce: lockedNonce,
          scopeKey,
          expectedFingerprint: expectedFp,
          actualFingerprint: payloadFingerprint,
        });
      }

      if (params.requireVerifiedRetry) {
        const auth = verifiedRetryAuthorizedNonces.get(lockedNonce);
        if (!auth) {
          throw new UnknownOutcomeLockBlockedError({
            errorCode: 'UNKNOWN_OUTCOME_LOCK_ACTIVE',
            scopeKey,
            nonce: lockedNonce,
            persistenceDegraded: inspected.degraded,
            message: `Retry blocked for '${lockedNonce}': check transaction status first to confirm it was not already recorded.`,
          });
        }
        if (auth.payloadFingerprint && auth.payloadFingerprint !== payloadFingerprint) {
          throw new PayloadMismatchError({
            nonce: lockedNonce,
            scopeKey,
            expectedFingerprint: auth.payloadFingerprint,
            actualFingerprint: payloadFingerprint,
          });
        }
      }
    }
  }

  // 2. Always check global nonce identity registry (catches direct apiRequest/apiFetch calls!)
  if (nonce) {
    const reg = nonceIdentityRegistry.get(nonce);
    if (reg) {
      if (reg.recoveryRequired || reg.transactionState === 'RECOVERY_REQUIRED') {
        throw new UnknownOutcomeLockBlockedError({
          errorCode: 'RECOVERY_REQUIRED_LOCKED',
          scopeKey: scopeKey || reg.scopeKey,
          nonce,
          message: `Retry blocked for nonce '${nonce}': transaction is quarantined in RECOVERY_REQUIRED state.`,
        });
      }
      if (reg.payloadFingerprint && reg.payloadFingerprint !== payloadFingerprint) {
        throw new PayloadMismatchError({
          nonce,
          scopeKey: scopeKey || reg.scopeKey,
          expectedFingerprint: reg.payloadFingerprint,
          actualFingerprint: payloadFingerprint,
        });
      }
    }
  }

  return { payloadFingerprint };
}

/**
 * Resets internal in-memory lock registries (strictly for automated unit tests).
 */
export function __resetUnknownLockRegistriesForTest(): void {
  memoryScopeLocks.clear();
  nonceIdentityRegistry.clear();
  verifiedRetryAuthorizedNonces.clear();
  verifiedTerminalResolvedNonces.clear();
}

// ---------------------------------------------------------------------------
// React Hook for Views (Phase 1 + Phase 2 + Phase 3)
// ---------------------------------------------------------------------------

/**
 * Reusable React hook that manages a view's UNKNOWN/RECOVERY_REQUIRED lock state with:
 * - Verified sessionStorage persistence + readback integrity check.
 * - Authoritative in-memory lock survival & visible safety-degraded mode on storage failures.
 * - Fail-closed lock on corrupted stored lock data.
 * - Deterministic canonical payload fingerprint recording & mismatch enforcement.
 * - Safe nonce creation guard & verified-only unlock.
 */
export function useUnknownOutcomeGuard(scopeKey: string) {
  const [initialInspection] = useState<LockPersistenceResult>(() =>
    inspectPersistedUnknownOutcome(scopeKey)
  );

  const [unknownOutcome, setUnknownOutcomeInternal] = useState<UnknownOutcomeState | null>(() => {
    if (initialInspection.record) {
      return initialInspection.record.outcome;
    }
    if (initialInspection.degraded && initialInspection.memoryLocked) {
      return buildDegradedCorruptedOutcome(
        scopeKey,
        initialInspection.status,
        initialInspection.errorMessage || 'Corrupted or unreadable UNKNOWN lock in storage.'
      );
    }
    return null;
  });

  const [payloadFingerprint, setPayloadFingerprint] = useState<string | undefined>(() => {
    return (
      initialInspection.record?.payloadFingerprint ||
      initialInspection.record?.outcome?.payloadFingerprint
    );
  });

  const [persistenceStatus, setPersistenceStatus] = useState<LockPersistenceStatus>(
    initialInspection.status
  );
  const [persistenceDegraded, setPersistenceDegraded] = useState<boolean>(
    initialInspection.degraded
  );
  const [persistenceFailureReason, setPersistenceFailureReason] = useState<string | null>(
    initialInspection.errorMessage || null
  );
  const [fingerprintMismatchError, setFingerprintMismatchError] = useState<string | null>(null);

  // Sync memory/storage when scopeKey changes
  useEffect(() => {
    const inspected = inspectPersistedUnknownOutcome(scopeKey);
    setPersistenceStatus(inspected.status);
    setPersistenceDegraded(inspected.degraded);
    setPersistenceFailureReason(inspected.errorMessage || null);
    if (inspected.record) {
      setUnknownOutcomeInternal(inspected.record.outcome);
      setPayloadFingerprint(
        inspected.record.payloadFingerprint || inspected.record.outcome.payloadFingerprint
      );
    } else if (inspected.degraded && inspected.memoryLocked) {
      setUnknownOutcomeInternal(
        buildDegradedCorruptedOutcome(
          scopeKey,
          inspected.status,
          inspected.errorMessage || 'Corrupted or unreadable UNKNOWN lock in storage.'
        )
      );
      setPayloadFingerprint(undefined);
    }
  }, [scopeKey]);

  const lockWithUnknownOutcome = useCallback(
    (nextOutcome: UnknownOutcomeState, payload?: unknown): LockPersistenceResult => {
      let fp: string | undefined = nextOutcome.payloadFingerprint;
      if (payload !== undefined) {
        try {
          fp = computePayloadFingerprint(payload);
        } catch (err: unknown) {
          // Fail closed: keep locked even if payload cannot be fingerprinted!
          const reason = err instanceof Error ? err.message : String(err);
          const degradedOutcome = enrichOutcomeWithLockMetadata(nextOutcome, {
            scopeKey,
            persistenceStatus: 'SET_ITEM_ERROR',
            persistenceDegraded: true,
            persistenceFailureReason: `Payload fingerprint could not be computed (${reason}). Form remains locked fail-closed.`,
            reloadSafe: false,
          });
          memoryScopeLocks.set(scopeKey, {
            scopeKey,
            record: nextOutcome.nonce
              ? {
                  version: 2,
                  scopeKey,
                  outcome: degradedOutcome,
                  preservedNonce: nextOutcome.nonce,
                  transactionId: nextOutcome.transactionId,
                  correlationId: nextOutcome.correlationId,
                  lockedAt: new Date().toISOString(),
                }
              : null,
            persistenceStatus: 'SET_ITEM_ERROR',
            degraded: true,
            reloadSafe: false,
            errorMessage: degradedOutcome.persistenceFailureReason,
            corruptedLockActive: !nextOutcome.nonce,
          });
          setUnknownOutcomeInternal(degradedOutcome);
          setPersistenceStatus('SET_ITEM_ERROR');
          setPersistenceDegraded(true);
          setPersistenceFailureReason(degradedOutcome.persistenceFailureReason || null);
          return {
            ok: false,
            persisted: false,
            verified: false,
            memoryLocked: true,
            degraded: true,
            reloadSafe: false,
            status: 'SET_ITEM_ERROR',
            errorMessage: degradedOutcome.persistenceFailureReason,
            record: null,
          };
        }
      }

      const result = persistUnknownOutcome(scopeKey, nextOutcome, fp);
      const lockedOutcome =
        result.record?.outcome ||
        enrichOutcomeWithLockMetadata(nextOutcome, {
          scopeKey,
          payloadFingerprint: fp,
          persistenceStatus: result.status,
          persistenceDegraded: result.degraded,
          persistenceFailureReason: result.errorMessage,
          reloadSafe: result.reloadSafe,
        });

      setPayloadFingerprint(result.record?.payloadFingerprint || fp);
      setUnknownOutcomeInternal(lockedOutcome);
      setPersistenceStatus(result.status);
      setPersistenceDegraded(result.degraded);
      setPersistenceFailureReason(result.errorMessage || null);
      setFingerprintMismatchError(null);
      return result;
    },
    [scopeKey]
  );

  const verifyPayloadMatchesLock = useCallback(
    (
      payload: unknown,
      nonce?: string
    ): { ok: true; payloadFingerprint: string } | { ok: false; error: string } => {
      try {
        const res = verifyPayloadAgainstActiveLock({
          scopeKey,
          nonce: nonce || unknownOutcome?.nonce,
          payload,
        });
        setFingerprintMismatchError(null);
        return { ok: true, payloadFingerprint: res.payloadFingerprint };
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setFingerprintMismatchError(msg);
        return { ok: false, error: msg };
      }
    },
    [scopeKey, unknownOutcome?.nonce]
  );

  const clearAfterVerifiedResolution = useCallback(
    (statusResponse?: Pick<TransactionStatusResponse, 'status'>) => {
      // If a statusResponse was passed, refuse to clear unless it is terminal!
      if (
        statusResponse &&
        statusResponse.status !== 'CONFIRMED_RECORDED' &&
        statusResponse.status !== 'RECONCILED'
      ) {
        return false;
      }
      setUnknownOutcomeInternal(null);
      setPayloadFingerprint(undefined);
      setFingerprintMismatchError(null);
      const clearRes = clearPersistedUnknownOutcome(scopeKey);
      if (clearRes.storageCleared) {
        setPersistenceStatus('IDLE');
        setPersistenceDegraded(false);
        setPersistenceFailureReason(null);
      } else {
        setPersistenceStatus('IDLE');
        setPersistenceDegraded(false);
        setPersistenceFailureReason(clearRes.errorMessage || null);
      }
      return true;
    },
    [scopeKey]
  );

  const setUnknownOutcome = useCallback(
    (next: UnknownOutcomeState | null, payload?: unknown) => {
      if (next && (next.nonce || next.persistenceDegraded)) {
        lockWithUnknownOutcome(next, payload);
      } else {
        clearAfterVerifiedResolution();
      }
    },
    [lockWithUnknownOutcome, clearAfterVerifiedResolution]
  );

  const locked = isOutcomeLocked(unknownOutcome) || (persistenceDegraded && isScopeLocked(scopeKey));

  return {
    unknownOutcome,
    isOutcomeLocked: locked,
    preservedNonce: unknownOutcome?.nonce || null,
    payloadFingerprint,
    persistenceStatus,
    persistenceDegraded,
    persistenceFailureReason,
    fingerprintMismatchError,
    verifyPayloadMatchesLock,
    setUnknownOutcome,
    lockWithUnknownOutcome,
    clearAfterVerifiedResolution,
  };
}
