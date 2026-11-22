/**
 * MISSION 51B-1R-F REGRESSION TEST SUITE
 * Frontend UNKNOWN-Outcome Lock Persistence Safety & Canonical Payload Fingerprint Enforcement.
 *
 * Covers every requirement in Phase 1 (Persistence Safety), Phase 2 (Payload Fingerprint Enforcement),
 * and Phase 3 (Frontend View Control-Flow Audit):
 *   Part A: Normal persistence & readback verification + remount/reload restoration.
 *   Part B: All storage failure modes (unavailable, setItem throw, QuotaExceededError,
 *           SecurityError / access denied, getItem throw, corrupted JSON/schema, readback mismatch).
 *   Part C: Memory lock survival, safety-degraded mode, submission & fresh-nonce blocking,
 *           safe reload-degraded signaling, and verified-only unlock rules.
 *   Part D: Deterministic canonicalization, SHA-256 fingerprinting, financial field sensitivity,
 *           and fail-closed behavior on uncomputable values.
 *   Part E: Transport-level enforcement in apiRequest & apiFetch (PayloadMismatchError,
 *           UnknownOutcomeLockBlockedError, zero network calls on blocked mutations,
 *           GET status-check passthrough, verified same-nonce retry vs modified payload).
 *   Part F: Static contract checks across UnknownOutcomeBanner and repaired views.
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  UNKNOWN_LOCK_STORAGE_PREFIX,
  PayloadFingerprintError,
  PayloadMismatchError,
  UnknownOutcomeLockBlockedError,
  canonicalizePayload,
  computePayloadFingerprint,
  computeRequestBodyFingerprint,
  persistUnknownOutcome,
  inspectPersistedUnknownOutcome,
  loadPersistedUnknownOutcome,
  clearPersistedUnknownOutcome,
  resolveAndClearUnknownOutcome,
  recordAuthoritativeStatusCheckResult,
  assertFreshNonceAllowed,
  verifyPayloadAgainstActiveLock,
  isScopeLocked,
  isNonceTerminallyResolved,
  getMemoryScopeLock,
  getRegisteredNonceIdentity,
  shouldBlockDraftNonceReset,
  __resetUnknownLockRegistriesForTest,
} from '../src/utils/unknownOutcomeLock';
import {
  apiRequest,
  apiFetch,
  checkV2TransactionStatus,
  ApiOutcomeUnknownError,
  ApiHttpError,
  isUnknownOutcomeError,
} from '../src/services/api';

// ---------------------------------------------------------------------------
// Test Runner Harness
// ---------------------------------------------------------------------------

interface TestResult {
  name: string;
  passed: boolean;
  error?: string;
}

const results: TestResult[] = [];

async function runTest(name: string, fn: () => Promise<void> | void) {
  __resetUnknownLockRegistriesForTest();
  installNormalWindowStorage();
  try {
    await fn();
    results.push({ name, passed: true });
    console.log(`  [PASS] ${name}`);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.stack || err.message : String(err);
    results.push({ name, passed: false, error: msg });
    console.error(`  [FAIL] ${name}\n    ${msg}`);
  }
}

// ---------------------------------------------------------------------------
// Configurable Mock sessionStorage / window Harness
// ---------------------------------------------------------------------------

function createMemoryStorage(overrides?: Partial<Storage>): Storage {
  const backing = new Map<string, string>();
  const base: Storage = {
    get length() {
      return backing.size;
    },
    clear() {
      backing.clear();
    },
    getItem(key: string) {
      return backing.has(key) ? backing.get(key)! : null;
    },
    key(index: number) {
      return Array.from(backing.keys())[index] ?? null;
    },
    removeItem(key: string) {
      backing.delete(key);
    },
    setItem(key: string, value: string) {
      backing.set(key, String(value));
    },
  };
  return Object.assign(base, overrides || {});
}

let activeSessionStorage: Storage | undefined;
let activeLocalStorage: Storage;

const MOCK_LOCATION = {
  hostname: 'localhost',
  origin: 'http://localhost:3000',
  protocol: 'http:',
};

function installNormalWindowStorage(customSession?: Storage | undefined) {
  activeSessionStorage = customSession ?? createMemoryStorage();
  activeLocalStorage = createMemoryStorage();
  const winObj: Record<string, unknown> = {
    location: MOCK_LOCATION,
    localStorage: activeLocalStorage,
    sessionStorage: activeSessionStorage,
    dispatchEvent: () => true,
  };
  Object.defineProperty(globalThis, 'window', {
    value: winObj,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(globalThis, 'localStorage', {
    value: activeLocalStorage,
    configurable: true,
    writable: true,
  });
}

function installThrowingSessionStorageGetter(err: Error) {
  activeLocalStorage = createMemoryStorage();
  const winObj: Record<string, unknown> = {
    location: MOCK_LOCATION,
    localStorage: activeLocalStorage,
    dispatchEvent: () => true,
  };
  Object.defineProperty(winObj, 'sessionStorage', {
    get() {
      throw err;
    },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'window', {
    value: winObj,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(globalThis, 'localStorage', {
    value: activeLocalStorage,
    configurable: true,
    writable: true,
  });
}

function installUnavailableSessionStorage() {
  activeLocalStorage = createMemoryStorage();
  const winObj: Record<string, unknown> = {
    location: MOCK_LOCATION,
    localStorage: activeLocalStorage,
    sessionStorage: undefined,
    dispatchEvent: () => true,
  };
  Object.defineProperty(globalThis, 'window', {
    value: winObj,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(globalThis, 'localStorage', {
    value: activeLocalStorage,
    configurable: true,
    writable: true,
  });
}

// ---------------------------------------------------------------------------
// Sample Financial Payloads
// ---------------------------------------------------------------------------

const SAMPLE_SALE_PAYLOAD = {
  customer_id: 'CUS-1001',
  customer_name_snapshot: 'Shree Ganesh Kirana',
  sales_type: 'WHOLESALE',
  payment_method: 'CASH',
  discount_amount: 50,
  bill_total: 1450,
  lines: [
    { product_id: 'PROD-DAL-500', quantity: 10, actual_unit_price: 150 },
  ],
};

// ---------------------------------------------------------------------------
// Main Test Suite Execution
// ---------------------------------------------------------------------------

async function main() {
  console.log('\n====================================================================');
  console.log('MISSION 51B-1R-F: FRONTEND LOCK PERSISTENCE & FINGERPRINT TESTS');
  console.log('====================================================================\n');

  // =========================================================================
  // PART A & B: PHASE 1 — UNKNOWN LOCK PERSISTENCE SAFETY
  // =========================================================================

  await runTest('1. Normal storage: persistUnknownOutcome writes, verifies readback, and preserves all identity fields', () => {
    const scope = 'sales_view';
    const fp = computePayloadFingerprint(SAMPLE_SALE_PAYLOAD);
    const res = persistUnknownOutcome(
      scope,
      {
        nonce: 'SALE-2026-0001',
        transactionId: 'TXN-9001',
        correlationId: 'CORR-9001',
        actionLabel: 'Issue Sales Bill',
        message: 'Transaction outcome unknown',
        transactionState: 'UNKNOWN',
      },
      SAMPLE_SALE_PAYLOAD
    );

    assert.equal(res.ok, true);
    assert.equal(res.persisted, true);
    assert.equal(res.verified, true);
    assert.equal(res.memoryLocked, true);
    assert.equal(res.degraded, false);
    assert.equal(res.reloadSafe, true);
    assert.equal(res.status, 'VERIFIED');
    assert.ok(res.record);
    assert.equal(res.record.scopeKey, scope);
    assert.equal(res.record.preservedNonce, 'SALE-2026-0001');
    assert.equal(res.record.transactionId, 'TXN-9001');
    assert.equal(res.record.correlationId, 'CORR-9001');
    assert.equal(res.record.payloadFingerprint, fp);
    assert.ok(res.record.lockedAt && res.record.lockedAt.length >= 20);
    assert.equal(isScopeLocked(scope), true);
  });

  await runTest('2. Remount / reload simulation when persistence succeeded: restores lock, nonce, and payload fingerprint', () => {
    const scope = 'sales_view';
    const fp = computePayloadFingerprint(SAMPLE_SALE_PAYLOAD);
    const persistRes = persistUnknownOutcome(
      scope,
      {
        nonce: 'SALE-RELOAD-1',
        transactionId: 'TXN-RLD-1',
        actionLabel: 'Issue Sales Bill',
        message: 'Timeout',
        transactionState: 'UNKNOWN',
      },
      SAMPLE_SALE_PAYLOAD
    );
    assert.equal(persistRes.status, 'VERIFIED');

    // Simulate full JS module reload / component remount: wipe all in-memory registries while keeping sessionStorage!
    __resetUnknownLockRegistriesForTest();
    assert.equal(getMemoryScopeLock(scope), null);
    assert.equal(getRegisteredNonceIdentity('SALE-RELOAD-1'), null);

    // Reload inspection restores lock + fingerprint and re-hydrates registries
    const inspected = inspectPersistedUnknownOutcome(scope);
    assert.equal(inspected.ok, true);
    assert.equal(inspected.persisted, true);
    assert.equal(inspected.verified, true);
    assert.equal(inspected.degraded, false);
    assert.equal(inspected.reloadSafe, true);
    assert.equal(inspected.record?.preservedNonce, 'SALE-RELOAD-1');
    assert.equal(inspected.record?.transactionId, 'TXN-RLD-1');
    assert.equal(inspected.record?.payloadFingerprint, fp);
    assert.equal(getRegisteredNonceIdentity('SALE-RELOAD-1')?.payloadFingerprint, fp);

    // Fresh nonce remains blocked after reload
    assert.throws(
      () => assertFreshNonceAllowed(scope),
      (err: unknown) => err instanceof UnknownOutcomeLockBlockedError && err.errorCode === 'FRESH_NONCE_BLOCKED'
    );

    // Modified payload with restored nonce is blocked after reload
    assert.throws(
      () =>
        verifyPayloadAgainstActiveLock({
          scopeKey: scope,
          nonce: 'SALE-RELOAD-1',
          payload: { ...SAMPLE_SALE_PAYLOAD, bill_total: 9999 },
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.nonce === 'SALE-RELOAD-1'
    );
  });

  await runTest('3. Storage unavailable: enters safety-degraded mode, maintains memory lock, blocks submissions & fresh nonces', () => {
    installUnavailableSessionStorage();
    const scope = 'sales_view';
    const res = persistUnknownOutcome(
      scope,
      { nonce: 'SALE-NOSTORE-1', message: 'Network drop', actionLabel: 'Issue Sales Bill' },
      SAMPLE_SALE_PAYLOAD
    );

    assert.equal(res.ok, false);
    assert.equal(res.persisted, false);
    assert.equal(res.verified, false);
    assert.equal(res.memoryLocked, true);
    assert.equal(res.degraded, true);
    assert.equal(res.reloadSafe, false);
    assert.equal(res.status, 'STORAGE_UNAVAILABLE');
    assert.ok(res.errorMessage && res.errorMessage.length > 0);
    assert.equal(res.record?.outcome.persistenceDegraded, true);
    assert.equal(res.record?.outcome.reloadSafe, false);

    // Memory lock stays active when inspected or loaded
    const loaded = loadPersistedUnknownOutcome(scope);
    assert.equal(loaded?.preservedNonce, 'SALE-NOSTORE-1');
    assert.equal(isScopeLocked(scope), true);

    // Fresh nonce and new submissions are blocked
    assert.throws(() => assertFreshNonceAllowed(scope), UnknownOutcomeLockBlockedError);
    assert.throws(
      () =>
        verifyPayloadAgainstActiveLock({
          scopeKey: scope,
          nonce: 'SALE-FRESH-99',
          payload: SAMPLE_SALE_PAYLOAD,
        }),
      UnknownOutcomeLockBlockedError
    );
  });

  await runTest('4. setItem throws generic Error: enters SET_ITEM_ERROR degraded mode, keeps memory lock & blocks submissions', () => {
    const broken = createMemoryStorage({
      setItem() {
        throw new Error('Disk I/O write failure');
      },
    });
    installNormalWindowStorage(broken);

    const scope = 'closing_view';
    const res = persistUnknownOutcome(
      scope,
      { nonce: 'CLS-SETFAIL-1', message: '504 Gateway Timeout', actionLabel: 'Daily Closing' },
      { opening_cash: 500, physical_cash_returned: 2300 }
    );

    assert.equal(res.ok, false);
    assert.equal(res.persisted, false);
    assert.equal(res.memoryLocked, true);
    assert.equal(res.degraded, true);
    assert.equal(res.reloadSafe, false);
    assert.equal(res.status, 'SET_ITEM_ERROR');
    assert.ok(res.errorMessage?.includes('Disk I/O write failure'));

    // Subsequent inspection does NOT drop memory lock even though storage returns null
    const inspected = inspectPersistedUnknownOutcome(scope);
    assert.equal(inspected.memoryLocked, true);
    assert.equal(inspected.degraded, true);
    assert.equal(inspected.reloadSafe, false);
    assert.equal(inspected.record?.preservedNonce, 'CLS-SETFAIL-1');

    // Submissions remain blocked
    assert.throws(
      () =>
        verifyPayloadAgainstActiveLock({
          scopeKey: scope,
          nonce: 'CLS-NEW-2',
          payload: { opening_cash: 500, physical_cash_returned: 2300 },
        }),
      UnknownOutcomeLockBlockedError
    );
  });

  await runTest('5. QuotaExceededError on setItem: classified as QUOTA_EXCEEDED, memory lock maintained, submissions blocked', () => {
    const quotaErr = new Error('Storage quota exceeded');
    quotaErr.name = 'QuotaExceededError';
    const broken = createMemoryStorage({
      setItem() {
        throw quotaErr;
      },
    });
    installNormalWindowStorage(broken);

    const scope = 'salary_view';
    const res = persistUnknownOutcome(
      scope,
      { nonce: 'SAL-QUOTA-1', message: 'Timeout', actionLabel: 'Calculate Payroll' },
      { salesman_user_id: 'USR-7', base_salary: 8000 }
    );

    assert.equal(res.ok, false);
    assert.equal(res.status, 'QUOTA_EXCEEDED');
    assert.equal(res.memoryLocked, true);
    assert.equal(res.degraded, true);
    assert.equal(res.reloadSafe, false);
    assert.equal(isScopeLocked(scope), true);
    assert.throws(() => assertFreshNonceAllowed(scope), UnknownOutcomeLockBlockedError);
  });

  await runTest('6. Storage access denied (SecurityError): classified as ACCESS_DENIED, memory lock maintained', () => {
    const secErr = new Error('Access is denied for this document');
    secErr.name = 'SecurityError';
    installThrowingSessionStorageGetter(secErr);

    const scope = 'expenses_view';
    const res = persistUnknownOutcome(
      scope,
      { nonce: 'EXP-SEC-1', message: '504', actionLabel: 'Submit Expense' },
      { category: 'FUEL', amount: 450 }
    );

    assert.equal(res.ok, false);
    assert.equal(res.status, 'ACCESS_DENIED');
    assert.equal(res.memoryLocked, true);
    assert.equal(res.degraded, true);
    assert.equal(res.reloadSafe, false);
    assert.equal(isScopeLocked(scope), true);
  });

  await runTest('7. getItem throws Error: fails CLOSED with READ_ERROR and blocks submissions in scope', () => {
    const brokenRead = createMemoryStorage({
      getItem() {
        throw new Error('Indexed storage read I/O error');
      },
    });
    installNormalWindowStorage(brokenRead);

    const scope = 'accounting_view';
    const inspected = inspectPersistedUnknownOutcome(scope);

    assert.equal(inspected.ok, false);
    assert.equal(inspected.status, 'READ_ERROR');
    assert.equal(inspected.memoryLocked, true);
    assert.equal(inspected.degraded, true);
    assert.equal(inspected.reloadSafe, false);
    assert.equal(isScopeLocked(scope), true);

    assert.throws(
      () => assertFreshNonceAllowed(scope),
      (err: unknown) => err instanceof UnknownOutcomeLockBlockedError && err.errorCode === 'LOCK_PERSISTENCE_DEGRADED'
    );
    assert.throws(
      () =>
        verifyPayloadAgainstActiveLock({
          scopeKey: scope,
          nonce: 'ACC-NEW-1',
          payload: { journal_id: 'JV-1' },
        }),
      (err: unknown) => err instanceof UnknownOutcomeLockBlockedError && err.errorCode === 'LOCK_PERSISTENCE_DEGRADED'
    );
  });

  await runTest('8. Corrupted JSON & malformed lock schema in sessionStorage: fail CLOSED (CORRUPTED_DATA) and block submissions', () => {
    const scope = 'purchasing_view';
    const storageKey = `${UNKNOWN_LOCK_STORAGE_PREFIX}${scope}`;

    // Case 8a: Truncated / invalid JSON
    activeSessionStorage!.setItem(storageKey, '{"preservedNonce":"PUR-1", CORRUPT_JSON');
    const badJson = inspectPersistedUnknownOutcome(scope);
    assert.equal(badJson.ok, false);
    assert.equal(badJson.status, 'CORRUPTED_DATA');
    assert.equal(badJson.memoryLocked, true);
    assert.equal(badJson.degraded, true);
    assert.equal(badJson.reloadSafe, false);
    assert.throws(() => assertFreshNonceAllowed(scope), UnknownOutcomeLockBlockedError);
    assert.throws(
      () => verifyPayloadAgainstActiveLock({ scopeKey: scope, nonce: 'PUR-NEW', payload: { amount: 500 } }),
      UnknownOutcomeLockBlockedError
    );

    // Case 8b: Valid JSON but tampered/mismatched nonce schema
    __resetUnknownLockRegistriesForTest();
    activeSessionStorage!.setItem(
      storageKey,
      JSON.stringify({
        preservedNonce: 'PUR-A',
        outcome: { nonce: 'PUR-DIFFERENT', message: 'tampered' },
        lockedAt: new Date().toISOString(),
      })
    );
    const badSchema = inspectPersistedUnknownOutcome(scope);
    assert.equal(badSchema.ok, false);
    assert.equal(badSchema.status, 'CORRUPTED_DATA');
    assert.equal(badSchema.memoryLocked, true);
    assert.equal(badSchema.degraded, true);
    assert.throws(() => assertFreshNonceAllowed(scope), UnknownOutcomeLockBlockedError);
  });

  await runTest('9. Persistence verification readback mismatch (silent drop / mutated readback): classified as READBACK_MISMATCH, memory locked', () => {
    const scope = 'workforce_view';
    // Storage that silently ignores setItem (simulating private browsing silent drop)
    const silentDropStorage = createMemoryStorage({
      setItem() {
        // intentionally drops write without throwing!
      },
      getItem() {
        return null;
      },
    });
    installNormalWindowStorage(silentDropStorage);

    const dropRes = persistUnknownOutcome(
      scope,
      { nonce: 'WF-DROP-1', message: '504', actionLabel: 'Disburse Payroll' },
      { amount: 12000 }
    );
    assert.equal(dropRes.ok, false);
    assert.equal(dropRes.persisted, false);
    assert.equal(dropRes.verified, false);
    assert.equal(dropRes.memoryLocked, true);
    assert.equal(dropRes.degraded, true);
    assert.equal(dropRes.reloadSafe, false);
    assert.equal(dropRes.status, 'READBACK_MISMATCH');

    // Storage that mutates written value on readback
    __resetUnknownLockRegistriesForTest();
    const mutatingStorage = createMemoryStorage({
      getItem(key: string) {
        if (key === `${UNKNOWN_LOCK_STORAGE_PREFIX}${scope}`) {
          return JSON.stringify({
            version: 2,
            scopeKey: scope,
            preservedNonce: 'WF-TAMPERED',
            outcome: { nonce: 'WF-TAMPERED', message: 'mutated' },
            payloadFingerprint: 'sha256:0000',
            lockedAt: new Date().toISOString(),
          });
        }
        return null;
      },
    });
    installNormalWindowStorage(mutatingStorage);

    const mutateRes = persistUnknownOutcome(
      scope,
      { nonce: 'WF-REAL-2', message: '504', actionLabel: 'Disburse Payroll' },
      { amount: 12000 }
    );
    assert.equal(mutateRes.ok, false);
    assert.equal(mutateRes.status, 'READBACK_MISMATCH');
    assert.equal(mutateRes.memoryLocked, true);
    assert.equal(mutateRes.degraded, true);
    assert.equal(mutateRes.reloadSafe, false);
    assert.equal(loadPersistedUnknownOutcome(scope)?.preservedNonce, 'WF-REAL-2');
  });

  await runTest('10. Safe behavior when persistence failed before reload & recovery rules (only authoritative terminal resolution unlocks)', () => {
    const scope = 'sales_view';
    const broken = createMemoryStorage({
      setItem() {
        throw new Error('Write blocked');
      },
    });
    installNormalWindowStorage(broken);

    const res = persistUnknownOutcome(
      scope,
      { nonce: 'SALE-DEG-1', message: '504', actionLabel: 'Issue Sales Bill' },
      SAMPLE_SALE_PAYLOAD
    );
    // Explicitly warns reload safety is NOT guaranteed before reload
    assert.equal(res.reloadSafe, false);
    assert.equal(res.degraded, true);
    assert.equal(res.record?.outcome.reloadSafe, false);
    assert.equal(res.record?.outcome.persistenceDegraded, true);
    assert.equal(shouldBlockDraftNonceReset(res.record?.outcome), true);

    // Non-terminal status checks MUST NOT unlock!
    recordAuthoritativeStatusCheckResult('SALE-DEG-1', {
      nonce: 'SALE-DEG-1',
      status: 'IN_PROGRESS',
      safe_to_retry_same_nonce: false,
    });
    assert.equal(isNonceTerminallyResolved('SALE-DEG-1'), false);
    assert.equal(isScopeLocked(scope), true);

    recordAuthoritativeStatusCheckResult('SALE-DEG-1', {
      nonce: 'SALE-DEG-1',
      status: 'UNKNOWN_STORAGE_UNAVAILABLE',
      safe_to_retry_same_nonce: false,
    });
    assert.equal(isNonceTerminallyResolved('SALE-DEG-1'), false);
    assert.equal(isScopeLocked(scope), true);

    const refused1 = resolveAndClearUnknownOutcome(scope, { status: 'IN_PROGRESS', nonce: 'SALE-DEG-1' });
    assert.equal(refused1.cleared, false);
    assert.equal(isScopeLocked(scope), true);

    const refused2 = resolveAndClearUnknownOutcome(scope, { status: 'RECOVERY_REQUIRED', nonce: 'SALE-DEG-1' });
    assert.equal(refused2.cleared, false);
    assert.equal(isScopeLocked(scope), true);

    const refused3 = resolveAndClearUnknownOutcome(scope, {
      status: 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE',
      nonce: 'SALE-DEG-1',
    });
    assert.equal(refused3.cleared, false);
    assert.equal(isScopeLocked(scope), true);

    // Authoritative terminal status (CONFIRMED_RECORDED) unlocks cleanly!
    recordAuthoritativeStatusCheckResult('SALE-DEG-1', {
      nonce: 'SALE-DEG-1',
      status: 'CONFIRMED_RECORDED',
      safe_to_retry_same_nonce: false,
    });
    assert.equal(isNonceTerminallyResolved('SALE-DEG-1'), true);

    const cleared = resolveAndClearUnknownOutcome(scope, {
      status: 'CONFIRMED_RECORDED',
      nonce: 'SALE-DEG-1',
    });
    assert.equal(cleared.cleared, true);
    assert.equal(isScopeLocked(scope), false);
    assert.doesNotThrow(() => assertFreshNonceAllowed(scope));
  });

  // =========================================================================
  // PART D: PHASE 2 — CANONICAL SERIALIZATION & PAYLOAD FINGERPRINTING
  // =========================================================================

  await runTest('11. Deterministic canonicalization & SHA-256: identical payloads & different key orders produce identical fingerprint', () => {
    const p1 = {
      customer_id: 'CUS-1',
      bill_total: 1200,
      discount_amount: 0,
      meta: { b: 2, a: 1, when: new Date('2026-11-22T10:00:00.000Z') },
      lines: [
        { sku: 'DAL-1', quantity: 4, price: 300 },
      ],
    };
    const p2 = {
      lines: [
        { price: 300, sku: 'DAL-1', quantity: 4 },
      ],
      meta: { when: new Date('2026-11-22T10:00:00.000Z'), a: 1, b: 2 },
      discount_amount: -0,
      bill_total: 1200,
      customer_id: 'CUS-1',
    };

    const c1 = canonicalizePayload(p1);
    const c2 = canonicalizePayload(p2);
    assert.equal(c1, c2);

    const fp1 = computePayloadFingerprint(p1);
    const fp2 = computePayloadFingerprint(p2);
    assert.match(fp1, /^sha256:[0-9a-f]{64}$/);
    assert.equal(fp1, fp2);
  });

  await runTest('12. Financial field sensitivity: bill total, discount, quantity, customer, and payment amount changes ALL alter fingerprint', () => {
    const baseFp = computePayloadFingerprint(SAMPLE_SALE_PAYLOAD);

    // 1. Bill total / amount change
    const diffTotal = computePayloadFingerprint({ ...SAMPLE_SALE_PAYLOAD, bill_total: 1451 });
    assert.notEqual(diffTotal, baseFp);

    // 2. Discount change
    const diffDiscount = computePayloadFingerprint({ ...SAMPLE_SALE_PAYLOAD, discount_amount: 55 });
    assert.notEqual(diffDiscount, baseFp);

    // 3. Quantity change inside nested line item
    const diffQty = computePayloadFingerprint({
      ...SAMPLE_SALE_PAYLOAD,
      lines: [{ product_id: 'PROD-DAL-500', quantity: 11, actual_unit_price: 150 }],
    });
    assert.notEqual(diffQty, baseFp);

    // 4. Customer change
    const diffCustomer = computePayloadFingerprint({
      ...SAMPLE_SALE_PAYLOAD,
      customer_id: 'CUS-2002',
    });
    assert.notEqual(diffCustomer, baseFp);

    // 5. Payment amount change
    const payBase = computePayloadFingerprint({ supplier_id: 'SUP-1', amount: 5000, mode: 'UPI' });
    const payChanged = computePayloadFingerprint({ supplier_id: 'SUP-1', amount: 5001, mode: 'UPI' });
    assert.notEqual(payChanged, payBase);
  });

  await runTest('13. Uncomputable payloads fail CLOSED with PayloadFingerprintError (NaN, Infinity, circular, Symbol, Function, BigInt, invalid Date, bad JSON)', () => {
    assert.throws(() => computePayloadFingerprint({ amount: Number.NaN }), PayloadFingerprintError);
    assert.throws(() => computePayloadFingerprint({ amount: Number.POSITIVE_INFINITY }), PayloadFingerprintError);
    assert.throws(() => computePayloadFingerprint({ amount: Number.NEGATIVE_INFINITY }), PayloadFingerprintError);
    assert.throws(() => computePayloadFingerprint({ fn: () => 1 }), PayloadFingerprintError);
    assert.throws(() => computePayloadFingerprint({ sym: Symbol('x') }), PayloadFingerprintError);
    assert.throws(() => computePayloadFingerprint({ big: BigInt(10) }), PayloadFingerprintError);
    assert.throws(() => computePayloadFingerprint({ dt: new Date('invalid-date') }), PayloadFingerprintError);

    const circular: Record<string, unknown> = { amount: 100 };
    circular.self = circular;
    assert.throws(() => computePayloadFingerprint(circular), PayloadFingerprintError);

    assert.throws(
      () => computeRequestBodyFingerprint('{not valid json', 'POST', '/api/sales'),
      PayloadFingerprintError
    );
  });

  // =========================================================================
  // PART E: PHASE 2 — TRANSPORT ENFORCEMENT IN apiRequest & apiFetch
  // =========================================================================

  await runTest('14. apiRequest: 504 records canonical fingerprint; modified payload with same unresolved nonce throws PayloadMismatchError with 0 fetch calls', async () => {
    const originalFetch = globalThis.fetch;
    let fetchCalls = 0;

    globalThis.fetch = (async () => {
      fetchCalls++;
      return new Response(
        JSON.stringify({
          detail: {
            message: 'Gateway timeout during commit',
            transaction_id: 'TXN-504-1',
            correlation_id: 'CORR-504-1',
            idempotency_key: 'SALE-FP-1',
            transaction_state: 'UNKNOWN',
          },
        }),
        { status: 504, headers: { 'Content-Type': 'application/json' } }
      );
    }) as typeof fetch;

    try {
      // Initial attempt times out (504 -> UNKNOWN)
      let caughtUnknown: unknown = null;
      try {
        await apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'SALE-FP-1',
          lockScope: 'sales_view',
          body: JSON.stringify(SAMPLE_SALE_PAYLOAD),
        });
      } catch (err) {
        caughtUnknown = err;
      }

      assert.ok(caughtUnknown instanceof ApiOutcomeUnknownError);
      assert.equal(fetchCalls, 1);
      const expectedFp = computePayloadFingerprint(SAMPLE_SALE_PAYLOAD);
      assert.equal(caughtUnknown.payloadFingerprint, expectedFp);

      // Persist scope lock as view does
      persistUnknownOutcome(
        'sales_view',
        {
          nonce: 'SALE-FP-1',
          transactionId: caughtUnknown.transactionId,
          message: caughtUnknown.message,
          payloadFingerprint: caughtUnknown.payloadFingerprint,
        },
        SAMPLE_SALE_PAYLOAD
      );

      // Attempt 2: Modified amount with SAME unresolved nonce -> MUST throw PayloadMismatchError with ZERO fetch calls!
      let mismatchErr: unknown = null;
      try {
        await apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'SALE-FP-1',
          lockScope: 'sales_view',
          body: JSON.stringify({ ...SAMPLE_SALE_PAYLOAD, bill_total: 2999 }),
        });
      } catch (err) {
        mismatchErr = err;
      }
      assert.ok(mismatchErr instanceof PayloadMismatchError, `Expected PayloadMismatchError, got ${String(mismatchErr)}`);
      assert.equal(mismatchErr.nonce, 'SALE-FP-1');
      assert.equal(mismatchErr.expectedFingerprint, expectedFp);
      assert.equal(fetchCalls, 1, 'Blocked modified payload must NOT make any network call');

      // Attempt 3: Fresh nonce bypass in locked scope -> MUST throw UnknownOutcomeLockBlockedError with ZERO fetch calls!
      let bypassErr: unknown = null;
      try {
        await apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'SALE-FRESH-BYPASS-2',
          lockScope: 'sales_view',
          body: JSON.stringify(SAMPLE_SALE_PAYLOAD),
        });
      } catch (err) {
        bypassErr = err;
      }
      assert.ok(bypassErr instanceof UnknownOutcomeLockBlockedError);
      assert.equal(bypassErr.errorCode, 'UNKNOWN_OUTCOME_LOCK_ACTIVE');
      assert.equal(fetchCalls, 1, 'Blocked fresh-nonce bypass must NOT make any network call');

      // Original unresolved nonce is still intact!
      assert.equal(loadPersistedUnknownOutcome('sales_view')?.preservedNonce, 'SALE-FP-1');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await runTest('15. apiFetch: blocks modified payload with unresolved nonce & fresh-nonce bypass; allows GET status-check & verified identical retry', async () => {
    const originalFetch = globalThis.fetch;
    let fetchCalls = 0;
    let mode: '504' | 'status_retry_safe' | 'retry_200' = '504';

    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      const url = String(input);
      if (url.includes('/api/v2/transactions/status/')) {
        return new Response(
          JSON.stringify({
            idempotency_key: 'WF-FP-1',
            status: 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE',
            safe_to_retry_same_nonce: true,
            message: 'No record found; safe to retry with same nonce.',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        );
      }
      if (mode === '504') {
        return new Response(
          JSON.stringify({ detail: { message: 'Gateway Timeout', transaction_state: 'UNKNOWN' } }),
          { status: 504, headers: { 'Content-Type': 'application/json' } }
        );
      }
      return new Response(JSON.stringify({ ok: true, id: 'PAY-100' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }) as typeof fetch;

    try {
      const payload = { recipient_id: 'EMP-9', amount: 15000, payment_method: 'BANK_TRANSFER' };
      const expectedFp = computePayloadFingerprint(payload);
      await assert.rejects(
        () =>
          apiFetch('/api/workforce/payments', {
            method: 'POST',
            idempotencyKey: 'WF-FP-1',
            lockScope: 'workforce_view',
            body: JSON.stringify(payload),
          }),
        (err: unknown) =>
          err instanceof ApiOutcomeUnknownError &&
          err.nonce === 'WF-FP-1' &&
          err.payloadFingerprint === expectedFp
      );
      assert.equal(fetchCalls, 1);

      persistUnknownOutcome(
        'workforce_view',
        { nonce: 'WF-FP-1', message: 'Timeout', actionLabel: 'Disburse Payroll' },
        payload
      );

      // Attempt unverified retry when requireVerifiedRetry=true -> blocked before fetch
      await assert.rejects(
        () =>
          apiFetch('/api/workforce/payments', {
            method: 'POST',
            idempotencyKey: 'WF-FP-1',
            lockScope: 'workforce_view',
            requireVerifiedRetry: true,
            body: JSON.stringify(payload),
          }),
        UnknownOutcomeLockBlockedError
      );
      assert.equal(fetchCalls, 1);

      // Status check (GET) MUST succeed even while scope is locked!
      mode = 'status_retry_safe';
      const statusRes = await checkV2TransactionStatus('WF-FP-1');
      assert.equal(statusRes.status, 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE');
      assert.equal(statusRes.safe_to_retry_same_nonce, true);
      assert.equal(fetchCalls, 2);

      // Even after NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE, a MODIFIED payload MUST STILL BE BLOCKED!
      await assert.rejects(
        () =>
          apiFetch('/api/workforce/payments', {
            method: 'POST',
            idempotencyKey: 'WF-FP-1',
            lockScope: 'workforce_view',
            requireVerifiedRetry: true,
            body: JSON.stringify({ ...payload, amount: 15500 }),
          }),
        PayloadMismatchError
      );
      assert.equal(fetchCalls, 2, 'Modified payload retry must still be blocked even after safe-to-retry status');

      // Exact canonical payload (even with different key order!) succeeds and clears lock!
      mode = 'retry_200';
      const reorderedIdentical = { payment_method: 'BANK_TRANSFER', amount: 15000, recipient_id: 'EMP-9' };
      const retryRes = await apiFetch('/api/workforce/payments', {
        method: 'POST',
        idempotencyKey: 'WF-FP-1',
        lockScope: 'workforce_view',
        requireVerifiedRetry: true,
        body: JSON.stringify(reorderedIdentical),
      });
      assert.equal(retryRes.status, 200);
      assert.equal(fetchCalls, 3);
      assert.equal(isScopeLocked('workforce_view'), false, 'Verified HTTP 200 retry must clear scope lock');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  await runTest('16. RECOVERY_REQUIRED blocks retries permanently even with identical payload until authoritative RECONCILED', async () => {
    const originalFetch = globalThis.fetch;
    let fetchCalls = 0;

    globalThis.fetch = (async () => {
      fetchCalls++;
      return new Response(
        JSON.stringify({
          detail: {
            error_code: 'RECOVERY_REQUIRED',
            transaction_state: 'RECOVERY_REQUIRED',
            transaction_id: 'TXN-Q-1',
            message: 'Accounting journal incomplete; quarantined for admin reconciliation.',
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } }
      );
    }) as typeof fetch;

    try {
      await assert.rejects(
        () =>
          apiRequest('/api/sales', {
            method: 'POST',
            idempotencyKey: 'SALE-QUAR-1',
            lockScope: 'sales_view',
            body: JSON.stringify(SAMPLE_SALE_PAYLOAD),
          }),
        (err: unknown) =>
          err instanceof ApiHttpError &&
          err.status === 409 &&
          isUnknownOutcomeError(err) &&
          err.transactionState === 'RECOVERY_REQUIRED'
      );
      assert.equal(fetchCalls, 1);

      // Even with identical payload & same nonce, retry is blocked with RECOVERY_REQUIRED_LOCKED!
      await assert.rejects(
        () =>
          apiRequest('/api/sales', {
            method: 'POST',
            idempotencyKey: 'SALE-QUAR-1',
            lockScope: 'sales_view',
            body: JSON.stringify(SAMPLE_SALE_PAYLOAD),
          }),
        (err: unknown) =>
          err instanceof UnknownOutcomeLockBlockedError && err.errorCode === 'RECOVERY_REQUIRED_LOCKED'
      );
      assert.equal(fetchCalls, 1, 'RECOVERY_REQUIRED retry must never hit network');

      // Authoritative RECONCILED resolves cleanly
      recordAuthoritativeStatusCheckResult('SALE-QUAR-1', {
        nonce: 'SALE-QUAR-1',
        status: 'RECONCILED',
        safe_to_retry_same_nonce: false,
      });
      const cleared = resolveAndClearUnknownOutcome('sales_view', {
        status: 'RECONCILED',
        nonce: 'SALE-QUAR-1',
      });
      assert.equal(cleared.cleared, true);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // =========================================================================
  // PART F: PHASE 3 — STATIC UI & VIEW SAFETY CONTRACT CHECKS
  // =========================================================================

  await runTest('17. Static contract: UnknownOutcomeBanner renders Safety-Degraded Mode, Payload Fingerprint & Mismatch alert without casual Dismiss', () => {
    const bannerSrc = fs.readFileSync(
      path.resolve(process.cwd(), 'src/components/common/UnknownOutcomeBanner.tsx'),
      'utf-8'
    );
    assert.ok(bannerSrc.includes('data-tx-degraded-persistence="true"'), 'Missing safety-degraded persistence banner attribute');
    assert.ok(bannerSrc.includes('Safety-Degraded Mode'), 'Missing visible Safety-Degraded Mode warning');
    assert.ok(bannerSrc.includes('data-tx-payload-mismatch="true"'), 'Missing payload mismatch alert attribute');
    assert.ok(bannerSrc.includes('Payload Fingerprint:'), 'Missing payload fingerprint display');
    assert.ok(bannerSrc.includes('Unlock Form (Verified)'), 'Missing verified-only unlock button');
    assert.equal(bannerSrc.includes('>Dismiss<'), false, 'Casual Dismiss button must not exist');
  });

  await runTest('18. Static contract: Primary financial & operational views guard nonce creation & enforce payload fingerprint checks', () => {
    const primaryViews = [
      'src/views/SalesView.tsx',
      'src/views/ClosingView.tsx',
      'src/views/SalaryView.tsx',
      'src/views/WorkforceView.tsx',
      'src/views/ExpensesView.tsx',
      'src/views/AccountingView.tsx',
    ];
    for (const rel of primaryViews) {
      const src = fs.readFileSync(path.resolve(process.cwd(), rel), 'utf-8');
      assert.ok(src.includes('verifyPayloadMatchesLock'), `${rel} must call verifyPayloadMatchesLock`);
      assert.ok(src.includes('fingerprintMismatchError'), `${rel} must wire fingerprintMismatchError to UnknownOutcomeBanner`);
    }

    // PurchasingView Apply-to-Bill & ProductionView nonce guards
    const purchasingSrc = fs.readFileSync(path.resolve(process.cwd(), 'src/views/PurchasingView.tsx'), 'utf-8');
    assert.ok(
      purchasingSrc.includes("if (isOutcomeLocked || shouldBlockDraftNonceReset(unknownOutcome)) return;") &&
        purchasingSrc.includes("createSubmissionNonce('ALLOC')"),
      'PurchasingView Apply-to-Bill must guard createSubmissionNonce behind isOutcomeLocked'
    );

    const productionSrc = fs.readFileSync(path.resolve(process.cwd(), 'src/views/ProductionView.tsx'), 'utf-8');
    assert.ok(
      productionSrc.includes('if (busy || !packagingId || isOutcomeLocked) return;'),
      'ProductionView handleRecoverPackaging must guard against isOutcomeLocked'
    );
    // Count guarded inline nonce handlers in ProductionView (16 inline + 1 handleRecoverPackaging = 17)
    const nonceMatches = productionSrc.match(/createSubmissionNonce\(/g) || [];
    const lockGuards = productionSrc.match(/if \(isOutcomeLocked\) return;/g) || [];
    assert.equal(nonceMatches.length, 17, `Expected 17 createSubmissionNonce calls in ProductionView, found ${nonceMatches.length}`);
    assert.ok(
      lockGuards.length >= 16,
      `Expected >=16 explicit isOutcomeLocked guards in ProductionView, found ${lockGuards.length}`
    );
  });

  // -------------------------------------------------------------------------
  // Summary
  // -------------------------------------------------------------------------
  const passed = results.filter((r) => r.passed).length;
  const failed = results.filter((r) => !r.passed).length;
  console.log('\n--------------------------------------------------------------------');
  console.log(`TOTAL: ${results.length} | PASSED: ${passed} | FAILED: ${failed} | SKIPPED: 0`);
  console.log('--------------------------------------------------------------------\n');

  if (failed > 0) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Unhandled test suite error:', err);
  process.exit(1);
});
