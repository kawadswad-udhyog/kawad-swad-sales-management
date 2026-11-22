/**
 * Mission 51B-1R-F2 — Comprehensive Behavioral Regression Suite
 * Target Defects: TX-FINAL-F-01 through TX-FINAL-F-05
 *
 * Covers all 39 required behavioral test scenarios across Groups A–E:
 *   Group A (1–8):   Request Identity & Bound Transaction Fingerprinting (TX-FINAL-F-01)
 *   Group B (9–15):  UNKNOWN Lock Persistence, Reload Hydration & Enforcement (TX-FINAL-F-02)
 *   Group C (16–22): Authoritative Status Response Identity Validation (TX-FINAL-F-03)
 *   Group D (23–30): Universal API Transport Lock & Scope Enforcement (TX-FINAL-F-04)
 *   Group E (31–39): Behavioral View / API Integration Across Critical Financial Paths (TX-FINAL-F-05)
 *
 * Strictly behavioral: exercises real transport, fingerprinting, persistence, status validation,
 * and exported API mutation functions against mocked fetch + sessionStorage (zero static-only shortcuts).
 */

import assert from 'node:assert/strict';

// ---------------------------------------------------------------------------
// Controlled Browser Storage Harness
// ---------------------------------------------------------------------------

function createMemoryStorage() {
  const map = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return map.size;
    },
    clear() {
      map.clear();
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null;
    },
    key(index: number) {
      return Array.from(map.keys())[index] ?? null;
    },
    removeItem(key: string) {
      map.delete(key);
    },
    setItem(key: string, value: string) {
      map.set(key, String(value));
    },
  };
  return { storage, map };
}

let sessionBacking = createMemoryStorage();
let localBacking = createMemoryStorage();

function resetBrowserEnvironment() {
  sessionBacking = createMemoryStorage();
  localBacking = createMemoryStorage();
  (globalThis as any).sessionStorage = sessionBacking.storage;
  (globalThis as any).localStorage = localBacking.storage;
  (globalThis as any).window = {
    location: { origin: 'http://localhost:3000', hostname: 'localhost' },
    sessionStorage: sessionBacking.storage,
    localStorage: localBacking.storage,
    dispatchEvent: () => true,
  };
}

resetBrowserEnvironment();

import {
  apiFetch,
  apiRequest,
  ApiOutcomeUnknownError,
  applySupplierAdvance,
  checkV2TransactionStatus,
  closeAccountingPeriod,
  createSalesOrder,
  createSupplierBill,
  executeReconciliation,
  PayloadFingerprintError,
  PayloadMismatchError,
  receiveRawMaterial,
  recordMillingBatch,
  recordSalePaymentApi,
  recordSupplierPayment,
  reverseJournalVoucherApi,
  setApiBaseUrl,
  StatusResponseValidationError,
  UnknownOutcomeLockBlockedError,
} from '../src/services/api.ts';
import {
  __resetUnknownLockRegistriesForTest,
  computePayloadFingerprint,
  computeTransactionIdentityFingerprint,
  inspectPersistedUnknownOutcome,
  isNonceTerminallyResolved,
  isScopeLocked,
  normalizeEndpointPath,
  normalizeHttpMethod,
  persistUnknownOutcome,
  recordAuthoritativeStatusCheckResult,
  resolveAndClearUnknownOutcome,
  resolveMutationTransactionScope,
  UNKNOWN_LOCK_STORAGE_PREFIX,
  validateAuthoritativeStatusResponse,
} from '../src/utils/unknownOutcomeLock.ts';

// ---------------------------------------------------------------------------
// Runner & Helpers
// ---------------------------------------------------------------------------

interface TestResult {
  id: number;
  group: string;
  name: string;
  passed: boolean;
  error?: string;
}

const results: TestResult[] = [];
const originalFetch = globalThis.fetch;

async function runCase(
  id: number,
  group: string,
  name: string,
  fn: () => void | Promise<void>
): Promise<void> {
  resetBrowserEnvironment();
  __resetUnknownLockRegistriesForTest();
  setApiBaseUrl('');
  globalThis.fetch = originalFetch;
  try {
    await fn();
    results.push({ id, group, name, passed: true });
    console.log(`  [PASS] ${id}. [${group}] ${name}`);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.stack || err.message : String(err);
    results.push({ id, group, name, passed: false, error: msg });
    console.error(`  [FAIL] ${id}. [${group}] ${name}\n${msg}`);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function mockStatusBody(
  nonce: string,
  status: string,
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    nonce,
    idempotency_key: nonce,
    status,
    safe_to_retry_same_nonce: status === 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE',
    checked_at: '2026-11-22T10:00:00.000Z',
    message: `Status ${status} for ${nonce}`,
    ...extra,
  };
}

function simulatePageReload(): void {
  // Wipe all in-memory registries while keeping sessionStorage intact (real page reload)
  __resetUnknownLockRegistriesForTest();
}

// ---------------------------------------------------------------------------
// Main Test Suite (39 Required Scenarios: Groups A–E)
// ---------------------------------------------------------------------------

async function main() {
  console.log('\n=== MISSION 51B-1R-F2 BEHAVIORAL REGRESSION SUITE (39 SCENARIOS) ===\n');

  // =========================================================================
  // TEST GROUP A — REQUEST IDENTITY (TX-FINAL-F-01)
  // =========================================================================

  await runCase(1, 'Group A', 'Same method + same endpoint + same payload -> identical transaction fingerprint', () => {
    const payload = { customer_id: 'CUS-10', bill_total: 4250.5, payment_mode: 'CASH' };
    const id1 = computeTransactionIdentityFingerprint({
      method: 'post',
      path: '/api/sales/',
      payload,
    });
    const id2 = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: 'https://kawad-swad.onrender.com/api/sales',
      payload: { payment_mode: 'CASH', bill_total: 4250.5, customer_id: 'CUS-10' },
    });
    assert.equal(id1.method, 'POST');
    assert.equal(id1.normalizedPath, '/api/sales');
    assert.equal(id1.normalizedPath, id2.normalizedPath);
    assert.equal(id1.payloadFingerprint, id2.payloadFingerprint);
    assert.equal(id1.transactionFingerprint, id2.transactionFingerprint);
    assert.match(id1.transactionFingerprint, /^sha256:[0-9a-f]{64}$/);
  });

  await runCase(2, 'Group A', 'Different HTTP method -> different transaction fingerprint', () => {
    const payload = { amount: 1500, notes: 'adjustment' };
    const postId = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/expenses/EXP-1',
      payload,
    });
    const putId = computeTransactionIdentityFingerprint({
      method: 'PUT',
      path: '/api/expenses/EXP-1',
      payload,
    });
    const patchId = computeTransactionIdentityFingerprint({
      method: 'PATCH',
      path: '/api/expenses/EXP-1',
      payload,
    });
    const delId = computeTransactionIdentityFingerprint({
      method: 'DELETE',
      path: '/api/expenses/EXP-1',
      payload,
    });
    assert.equal(postId.payloadFingerprint, putId.payloadFingerprint);
    const fps = new Set([
      postId.transactionFingerprint,
      putId.transactionFingerprint,
      patchId.transactionFingerprint,
      delId.transactionFingerprint,
    ]);
    assert.equal(fps.size, 4, 'Each HTTP method must yield a distinct transaction fingerprint');
  });

  await runCase(3, 'Group A', 'Different endpoint/path -> different transaction fingerprint', () => {
    const payload = { amount: 5000, ref: 'REF-1' };
    const a = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/purchasing/bills',
      payload,
    });
    const b = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/purchasing/payments',
      payload,
    });
    const c = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload,
    });
    assert.equal(a.payloadFingerprint, b.payloadFingerprint);
    assert.notEqual(a.transactionFingerprint, b.transactionFingerprint);
    assert.notEqual(a.transactionFingerprint, c.transactionFingerprint);
    assert.notEqual(b.transactionFingerprint, c.transactionFingerprint);
  });

  await runCase(4, 'Group A', 'Different payload -> different transaction fingerprint', () => {
    const a = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload: { customer_id: 'CUS-1', amount: 1000 },
    });
    const b = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload: { customer_id: 'CUS-1', amount: 1001 },
    });
    assert.notEqual(a.payloadFingerprint, b.payloadFingerprint);
    assert.notEqual(a.transactionFingerprint, b.transactionFingerprint);
  });

  await runCase(5, 'Group A', 'Query-string rules: reordered identical params match; changed/added/removed params differ', () => {
    const payload = { reason: 'year-end' };
    const q1 = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/accounting/reconcile?dry_run=false&confirm_live_backfill=true',
      payload,
    });
    const q2 = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/accounting/reconcile/?confirm_live_backfill=true&dry_run=false#section',
      payload,
    });
    const qChanged = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/accounting/reconcile?dry_run=true&confirm_live_backfill=true',
      payload,
    });
    const qRemoved = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/accounting/reconcile?dry_run=false',
      payload,
    });
    const qNone = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/accounting/reconcile',
      payload,
    });

    assert.equal(
      q1.normalizedPath,
      '/api/accounting/reconcile?confirm_live_backfill=true&dry_run=false'
    );
    assert.equal(q1.normalizedPath, q2.normalizedPath);
    assert.equal(q1.transactionFingerprint, q2.transactionFingerprint);
    assert.notEqual(q1.transactionFingerprint, qChanged.transactionFingerprint);
    assert.notEqual(q1.transactionFingerprint, qRemoved.transactionFingerprint);
    assert.notEqual(q1.transactionFingerprint, qNone.transactionFingerprint);
  });

  await runCase(6, 'Group A', 'Canonical key ordering (nested objects, -0, Date ISO) -> identical fingerprint', () => {
    const d = new Date('2026-11-22T08:30:00.000Z');
    const a = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/purchasing/bills',
      payload: {
        supplier_id: 'SUP-1',
        discount: -0,
        posted_at: d,
        lines: [{ qty: 10, product_id: 'RM-1', rate: 85.5 }],
      },
    });
    const b = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/purchasing/bills',
      payload: {
        lines: [{ rate: 85.5, product_id: 'RM-1', qty: 10 }],
        posted_at: '2026-11-22T08:30:00.000Z',
        discount: 0,
        supplier_id: 'SUP-1',
      },
    });
    assert.equal(a.payloadFingerprint, b.payloadFingerprint);
    assert.equal(a.transactionFingerprint, b.transactionFingerprint);
  });

  await runCase(7, 'Group A', 'Financial value sensitivity: amount, qty, rate, discount, tax, line order, recipient/account changes all differ', () => {
    const base = {
      customer_id: 'CUS-1',
      account_code: '4001',
      amount: 1000,
      discount: 50,
      tax: 95,
      lines: [
        { sku: 'A', qty: 2, rate: 250 },
        { sku: 'B', qty: 1, rate: 500 },
      ],
    };
    const baseFp = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload: base,
    }).transactionFingerprint;

    const mutations = [
      { ...base, amount: 1000.01 },
      { ...base, discount: 51 },
      { ...base, tax: 96 },
      { ...base, customer_id: 'CUS-2' },
      { ...base, account_code: '4002' },
      { ...base, lines: [{ sku: 'A', qty: 3, rate: 250 }, { sku: 'B', qty: 1, rate: 500 }] },
      { ...base, lines: [{ sku: 'A', qty: 2, rate: 250.5 }, { sku: 'B', qty: 1, rate: 500 }] },
      { ...base, lines: [base.lines[1], base.lines[0]] },
    ];

    for (const mutated of mutations) {
      const fp = computeTransactionIdentityFingerprint({
        method: 'POST',
        path: '/api/sales',
        payload: mutated,
      }).transactionFingerprint;
      assert.notEqual(fp, baseFp, 'Financially meaningful change MUST alter transaction fingerprint');
    }
  });

  await runCase(8, 'Group A', 'Fingerprint computation errors fail closed and block transmission with 0 fetch calls', async () => {
    // Circular reference, NaN, Infinity, invalid method, path traversal
    const circular: Record<string, unknown> = { a: 1 };
    circular.self = circular;
    assert.throws(
      () => computeTransactionIdentityFingerprint({ method: 'POST', path: '/api/sales', payload: circular }),
      PayloadFingerprintError
    );
    assert.throws(
      () => computeTransactionIdentityFingerprint({ method: 'POST', path: '/api/sales', payload: { amount: Number.NaN } }),
      PayloadFingerprintError
    );
    assert.throws(
      () => computeTransactionIdentityFingerprint({ method: 'POST', path: '/api/sales', payload: { amount: Infinity } }),
      PayloadFingerprintError
    );
    assert.throws(() => normalizeHttpMethod('INVALID_VERB'), PayloadFingerprintError);
    assert.throws(() => normalizeEndpointPath('/api/sales/../admin'), PayloadFingerprintError);
    assert.throws(() => normalizeEndpointPath('   '), PayloadFingerprintError);

    // Transport must block malformed JSON body with ZERO fetch calls
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-BAD-JSON',
          body: '{invalid-json',
        }),
      PayloadFingerprintError
    );
    await assert.rejects(
      () =>
        apiFetch('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-BAD-JSON-2',
          body: '{invalid-json',
        }),
      PayloadFingerprintError
    );
    assert.equal(fetchCalls, 0, 'Uncomputable fingerprint MUST block transmission with 0 network calls');
  });

  // =========================================================================
  // TEST GROUP B — UNKNOWN LOCK PERSISTENCE & ENFORCEMENT (TX-FINAL-F-02)
  // =========================================================================

  await runCase(9, 'Group B', 'Persisted lock stores & restores full request identity (method, path, payloadFingerprint, transactionFingerprint) across page reload', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse(
        { detail: { message: 'Gateway timeout', transaction_id: 'TXN-RELOAD-1', correlation_id: 'CORR-RELOAD-1' } },
        504
      );
    }) as typeof fetch;

    const payload = { customer_id: 'CUS-77', amount: 2400 };
    const expectedIdentity = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales?channel=van&mode=direct',
      payload,
    });

    await assert.rejects(
      () =>
        apiRequest('/api/sales?mode=direct&channel=van', {
          method: 'POST',
          idempotencyKey: 'NONCE-RELOAD-1',
          body: JSON.stringify(payload),
        }),
      (err: unknown) =>
        err instanceof ApiOutcomeUnknownError &&
        err.method === 'POST' &&
        err.path === '/api/sales?channel=van&mode=direct' &&
        err.payloadFingerprint === expectedIdentity.payloadFingerprint &&
        err.transactionFingerprint === expectedIdentity.transactionFingerprint
    );
    assert.equal(fetchCalls, 1);

    // Simulate full browser page reload (clear in-memory registries; keep sessionStorage)
    simulatePageReload();

    const inspected = inspectPersistedUnknownOutcome('sales_view');
    assert.equal(inspected.ok, true);
    assert.equal(inspected.verified, true);
    assert.equal(inspected.record?.version, 3);
    assert.equal(inspected.record?.preservedNonce, 'NONCE-RELOAD-1');
    assert.equal(inspected.record?.method, 'POST');
    assert.equal(inspected.record?.path, '/api/sales?channel=van&mode=direct');
    assert.equal(inspected.record?.payloadFingerprint, expectedIdentity.payloadFingerprint);
    assert.equal(inspected.record?.transactionFingerprint, expectedIdentity.transactionFingerprint);
    assert.equal(inspected.record?.transactionId, 'TXN-RELOAD-1');
    assert.equal(inspected.record?.correlationId, 'CORR-RELOAD-1');
    assert.ok(inspected.record?.lockedAt);
  });

  await runCase(10, 'Group B', 'Same-nonce identical recovery permitted under valid rules (including after reload & with reordered keys)', async () => {
    let fetchCalls = 0;
    let phase: 'timeout' | 'status' | 'retry' = 'timeout';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      const url = String(input);
      if (url.includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('NONCE-REC-OK', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (phase === 'timeout') {
        return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      }
      return jsonResponse({ ok: true, id: 'SL-900' }, 200);
    }) as typeof fetch;

    const originalPayload = { customer_id: 'CUS-9', amount: 3300, payment_mode: 'UPI' };
    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-REC-OK',
          body: JSON.stringify(originalPayload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);

    simulatePageReload();
    assert.equal(isScopeLocked('sales_view'), true);

    phase = 'status';
    const status = await checkV2TransactionStatus('NONCE-REC-OK');
    assert.equal(status.status, 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE');
    assert.equal(fetchCalls, 2);

    phase = 'retry';
    const res = await apiRequest<{ ok: boolean; id: string }>('/api/sales', {
      method: 'POST',
      idempotencyKey: 'NONCE-REC-OK',
      requireVerifiedRetry: true,
      body: JSON.stringify({ payment_mode: 'UPI', amount: 3300, customer_id: 'CUS-9' }),
    });
    assert.equal(res.ok, true);
    assert.equal(fetchCalls, 3);
    assert.equal(isScopeLocked('sales_view'), false);
  });

  await runCase(11, 'Group B', 'Same-nonce different-method blocked (before & after reload, 0 fetch calls)', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ detail: { message: 'Timeout' } }, 504);
    }) as typeof fetch;

    const payload = { status: 'APPROVED', notes: 'ok' };
    await assert.rejects(
      () =>
        apiRequest('/api/expenses/EXP-10', {
          method: 'POST',
          idempotencyKey: 'NONCE-METH-1',
          body: JSON.stringify(payload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);

    // Before reload: PUT with same nonce & same payload -> blocked
    await assert.rejects(
      () =>
        apiRequest('/api/expenses/EXP-10', {
          method: 'PUT',
          idempotencyKey: 'NONCE-METH-1',
          body: JSON.stringify(payload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'METHOD_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    // After reload: PATCH with same nonce & same payload -> still blocked!
    simulatePageReload();
    await assert.rejects(
      () =>
        apiRequest('/api/expenses/EXP-10', {
          method: 'PATCH',
          idempotencyKey: 'NONCE-METH-1',
          body: JSON.stringify(payload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'METHOD_MISMATCH'
    );
    assert.equal(fetchCalls, 1, 'Different-method reuse MUST cause 0 network calls');
  });

  await runCase(12, 'Group B', 'Same-nonce different-endpoint (and changed query string) blocked (before & after reload, 0 fetch calls)', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ detail: { message: 'Timeout' } }, 504);
    }) as typeof fetch;

    const payload = { amount: 7500 };
    await assert.rejects(
      () =>
        apiRequest('/api/purchasing/bills', {
          method: 'POST',
          idempotencyKey: 'NONCE-PATH-1',
          body: JSON.stringify(payload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);

    // Different endpoint path in same scope -> blocked
    await assert.rejects(
      () =>
        apiRequest('/api/purchasing/payments', {
          method: 'POST',
          idempotencyKey: 'NONCE-PATH-1',
          body: JSON.stringify(payload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    // After reload: added query string on same endpoint -> blocked!
    simulatePageReload();
    await assert.rejects(
      () =>
        apiRequest('/api/purchasing/bills?force=true', {
          method: 'POST',
          idempotencyKey: 'NONCE-PATH-1',
          body: JSON.stringify(payload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    assert.equal(fetchCalls, 1, 'Different-endpoint reuse MUST cause 0 network calls');
  });

  await runCase(13, 'Group B', 'Same-nonce different-payload blocked (before & after reload, 0 fetch calls)', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ detail: { message: 'Timeout' } }, 504);
    }) as typeof fetch;

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-PAY-1',
          body: JSON.stringify({ customer_id: 'CUS-1', amount: 500 }),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);

    simulatePageReload();

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-PAY-1',
          body: JSON.stringify({ customer_id: 'CUS-1', amount: 900 }),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'PAYLOAD_MISMATCH'
    );
    assert.equal(fetchCalls, 1, 'Different-payload reuse MUST cause 0 network calls');
  });

  await runCase(14, 'Group B', 'Fresh nonce cannot bypass active scope lock (before & after reload, 0 fetch calls)', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ detail: { message: 'Timeout' } }, 504);
    }) as typeof fetch;

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-LOCK-ORIG',
          body: JSON.stringify({ customer_id: 'CUS-1', amount: 1200 }),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);

    simulatePageReload();

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-FRESH-BYPASS',
          body: JSON.stringify({ customer_id: 'CUS-2', amount: 500 }),
        }),
      (err: unknown) =>
        err instanceof UnknownOutcomeLockBlockedError &&
        err.errorCode === 'UNKNOWN_OUTCOME_LOCK_ACTIVE'
    );
    assert.equal(fetchCalls, 1, 'Fresh-nonce bypass MUST cause 0 network calls');
  });

  await runCase(15, 'Group B', 'Malformed or incomplete persisted identity fails closed (CORRUPTED_DATA, 0 fetch calls)', async () => {
    const validPayloadFp = computePayloadFingerprint({ amount: 100 });
    const badRecords: Array<{ label: string; record: Record<string, unknown> }> = [
      {
        label: 'method without path',
        record: {
          version: 2,
          scopeKey: 'sales_view',
          preservedNonce: 'N-CORR-1',
          outcome: { nonce: 'N-CORR-1', message: 'timeout' },
          method: 'POST',
          payloadFingerprint: validPayloadFp,
          lockedAt: '2026-11-22T10:00:00.000Z',
        },
      },
      {
        label: 'path without method',
        record: {
          version: 2,
          scopeKey: 'sales_view',
          preservedNonce: 'N-CORR-2',
          outcome: { nonce: 'N-CORR-2', message: 'timeout' },
          path: '/api/sales',
          payloadFingerprint: validPayloadFp,
          lockedAt: '2026-11-22T10:00:00.000Z',
        },
      },
      {
        label: 'v3 missing transactionFingerprint',
        record: {
          version: 3,
          scopeKey: 'sales_view',
          preservedNonce: 'N-CORR-3',
          outcome: { nonce: 'N-CORR-3', message: 'timeout' },
          method: 'POST',
          path: '/api/sales',
          payloadFingerprint: validPayloadFp,
          lockedAt: '2026-11-22T10:00:00.000Z',
        },
      },
      {
        label: 'tampered transactionFingerprint mismatch',
        record: {
          version: 3,
          scopeKey: 'sales_view',
          preservedNonce: 'N-CORR-4',
          outcome: { nonce: 'N-CORR-4', message: 'timeout', method: 'POST', path: '/api/sales' },
          method: 'POST',
          path: '/api/sales',
          payloadFingerprint: validPayloadFp,
          transactionFingerprint: `sha256:${'f'.repeat(64)}`,
          lockedAt: '2026-11-22T10:00:00.000Z',
        },
      },
    ];

    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    for (const item of badRecords) {
      resetBrowserEnvironment();
      __resetUnknownLockRegistriesForTest();
      sessionBacking.storage.setItem(
        `${UNKNOWN_LOCK_STORAGE_PREFIX}sales_view`,
        JSON.stringify(item.record)
      );

      const inspected = inspectPersistedUnknownOutcome('sales_view');
      assert.equal(inspected.status, 'CORRUPTED_DATA', `${item.label} must classify CORRUPTED_DATA`);
      assert.equal(inspected.degraded, true);
      assert.equal(inspected.memoryLocked, true);
      assert.equal(isScopeLocked('sales_view'), true);

      await assert.rejects(
        () =>
          apiRequest('/api/sales', {
            method: 'POST',
            idempotencyKey: 'NONCE-AFTER-CORRUPT',
            body: JSON.stringify({ amount: 100 }),
          }),
        (err: unknown) =>
          err instanceof UnknownOutcomeLockBlockedError &&
          err.errorCode === 'LOCK_PERSISTENCE_DEGRADED'
      );
    }
    assert.equal(fetchCalls, 0, 'Malformed/incomplete persisted lock MUST fail closed with 0 fetch calls');
  });

  // =========================================================================
  // TEST GROUP C — STATUS RESPONSE IDENTITY (TX-FINAL-F-03)
  // =========================================================================

  await runCase(16, 'Group C', 'Correct response nonce (nonce or idempotency_key) accepted', async () => {
    globalThis.fetch = (async () =>
      jsonResponse({
        idempotency_key: 'NONCE-ST-OK',
        status: 'CONFIRMED_RECORDED',
        safe_to_retry_same_nonce: false,
        transaction_id: 'TXN-ST-1',
        checked_at: '2026-11-22T10:00:00.000Z',
        message: 'Confirmed recorded',
      })) as typeof fetch;

    const res = await checkV2TransactionStatus('NONCE-ST-OK', undefined, 'TXN-ST-1');
    assert.equal(res.nonce, 'NONCE-ST-OK');
    assert.equal(res.status, 'CONFIRMED_RECORDED');
    assert.equal(isNonceTerminallyResolved('NONCE-ST-OK'), true);
  });

  await runCase(17, 'Group C', 'Wrong response nonce (or conflicting nonce/idempotency_key or txId mismatch) rejected fail-closed', async () => {
    // 17a. Different response nonce
    globalThis.fetch = (async () =>
      jsonResponse(mockStatusBody('NONCE-OTHER-TX', 'CONFIRMED_RECORDED'))) as typeof fetch;

    await assert.rejects(
      () => checkV2TransactionStatus('NONCE-MINE'),
      (err: unknown) =>
        err instanceof StatusResponseValidationError && err.errorCode === 'NONCE_MISMATCH'
    );

    // 17b. Conflicting nonce vs idempotency_key
    assert.throws(
      () =>
        validateAuthoritativeStatusResponse('NONCE-MINE', {
          nonce: 'NONCE-MINE',
          idempotency_key: 'NONCE-OTHER',
          status: 'CONFIRMED_RECORDED',
          safe_to_retry_same_nonce: false,
        }),
      (err: unknown) =>
        err instanceof StatusResponseValidationError && err.errorCode === 'NONCE_MISMATCH'
    );

    // 17c. Transaction ID mismatch against locked transaction
    assert.throws(
      () =>
        validateAuthoritativeStatusResponse(
          'NONCE-MINE',
          mockStatusBody('NONCE-MINE', 'CONFIRMED_RECORDED', { transaction_id: 'TXN-WRONG' }),
          'TXN-EXPECTED'
        ),
      (err: unknown) =>
        err instanceof StatusResponseValidationError && err.errorCode === 'TRANSACTION_ID_MISMATCH'
    );
  });

  await runCase(18, 'Group C', 'Missing response nonce rejected fail-closed', async () => {
    globalThis.fetch = (async () =>
      jsonResponse({
        status: 'CONFIRMED_RECORDED',
        safe_to_retry_same_nonce: false,
        message: 'Confirmed without nonce',
      })) as typeof fetch;

    await assert.rejects(
      () => checkV2TransactionStatus('NONCE-MISS-1'),
      (err: unknown) =>
        err instanceof StatusResponseValidationError && err.errorCode === 'MISSING_RESPONSE_NONCE'
    );

    assert.throws(
      () =>
        recordAuthoritativeStatusCheckResult('NONCE-MISS-1', {
          nonce: '   ',
          status: 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE',
          safe_to_retry_same_nonce: true,
        }),
      (err: unknown) =>
        err instanceof StatusResponseValidationError && err.errorCode === 'MISSING_RESPONSE_NONCE'
    );
  });

  await runCase(19, 'Group C', 'Malformed status response (null, array, primitive, non-string nonce, non-boolean retry flag) rejected', async () => {
    for (const bad of [null, 'CONFIRMED_RECORDED', 123, ['CONFIRMED_RECORDED'], { nonce: 999, status: 'CONFIRMED_RECORDED' }]) {
      assert.throws(
        () => validateAuthoritativeStatusResponse('NONCE-MAL-1', bad),
        (err: unknown) =>
          err instanceof StatusResponseValidationError &&
          err.errorCode === 'MALFORMED_STATUS_RESPONSE'
      );
    }

    assert.throws(
      () =>
        validateAuthoritativeStatusResponse('NONCE-MAL-1', {
          nonce: 'NONCE-MAL-1',
          status: 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE',
          safe_to_retry_same_nonce: 'yes',
        }),
      (err: unknown) =>
        err instanceof StatusResponseValidationError && err.errorCode === 'INVALID_RETRY_FLAG'
    );
  });

  await runCase(20, 'Group C', 'Unknown / unrecognized status value rejected fail-closed', async () => {
    for (const badStatus of ['SUCCESS', 'COMPLETED', 'OK', 'PENDING', '', undefined]) {
      globalThis.fetch = (async () =>
        jsonResponse({
          nonce: 'NONCE-UNK-ST',
          status: badStatus,
          safe_to_retry_same_nonce: false,
        })) as typeof fetch;

      await assert.rejects(
        () => checkV2TransactionStatus('NONCE-UNK-ST'),
        (err: unknown) =>
          err instanceof StatusResponseValidationError && err.errorCode === 'UNKNOWN_STATUS_VALUE'
      );
    }
  });

  await runCase(21, 'Group C', 'Invalid status response CANNOT unlock scope or clear UNKNOWN lock', async () => {
    const payload = { customer_id: 'CUS-1', amount: 1500 };
    const id = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload,
    });
    persistUnknownOutcome(
      'sales_view',
      { nonce: 'NONCE-LOCKED-C21', transactionId: 'TXN-C21', message: 'Timeout' },
      payload,
      { method: id.method, path: id.normalizedPath, transactionFingerprint: id.transactionFingerprint }
    );
    assert.equal(isScopeLocked('sales_view'), true);

    const invalidResponses = [
      mockStatusBody('NONCE-DIFFERENT', 'CONFIRMED_RECORDED'),
      { status: 'CONFIRMED_RECORDED', safe_to_retry_same_nonce: false },
      mockStatusBody('NONCE-LOCKED-C21', 'BOGUS_STATUS'),
      mockStatusBody('NONCE-LOCKED-C21', 'RECONCILED', { transaction_id: 'TXN-OTHER' }),
    ];

    for (const badResp of invalidResponses) {
      globalThis.fetch = (async () => jsonResponse(badResp)) as typeof fetch;
      await assert.rejects(() => checkV2TransactionStatus('NONCE-LOCKED-C21'), StatusResponseValidationError);
      assert.equal(isNonceTerminallyResolved('NONCE-LOCKED-C21'), false);
      assert.equal(isScopeLocked('sales_view'), true);

      const clearAttempt = resolveAndClearUnknownOutcome('sales_view', {
        status: 'CONFIRMED_RECORDED',
        nonce: 'NONCE-LOCKED-C21',
        statusResponse: badResp,
      });
      assert.equal(clearAttempt.cleared, false, 'Invalid status response MUST NOT clear lock');
      assert.equal(isScopeLocked('sales_view'), true);
    }
  });

  await runCase(22, 'Group C', 'Invalid status response CANNOT authorize same-nonce retry', async () => {
    const payload = { customer_id: 'CUS-1', amount: 1500 };
    const id = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload,
    });
    persistUnknownOutcome(
      'sales_view',
      { nonce: 'NONCE-LOCKED-C22', message: 'Timeout' },
      payload,
      { method: id.method, path: id.normalizedPath, transactionFingerprint: id.transactionFingerprint }
    );

    // Server returns NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE for a DIFFERENT nonce
    globalThis.fetch = (async () =>
      jsonResponse(mockStatusBody('NONCE-SOMEONE-ELSE', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'))) as typeof fetch;

    await assert.rejects(
      () => checkV2TransactionStatus('NONCE-LOCKED-C22'),
      StatusResponseValidationError
    );

    // Retry attempt MUST STILL BE BLOCKED with 0 network calls
    let retryFetchCalls = 0;
    globalThis.fetch = (async () => {
      retryFetchCalls++;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-LOCKED-C22',
          requireVerifiedRetry: true,
          body: JSON.stringify(payload),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(retryFetchCalls, 0, 'Invalid status response must NEVER authorize retry');
  });

  // =========================================================================
  // TEST GROUP D — API TRANSPORT ENFORCEMENT (TX-FINAL-F-04)
  // =========================================================================

  await runCase(23, 'Group D', 'Mutation with active lock blocked before fetch in both apiRequest and apiFetch', async () => {
    persistUnknownOutcome('sales_view', { nonce: 'NONCE-D23-S', message: 'Locked' }, { amount: 100 });
    persistUnknownOutcome('workforce_view', { nonce: 'NONCE-D23-W', message: 'Locked' }, { amount: 200 });

    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-NEW-S',
          body: JSON.stringify({ amount: 500 }),
        }),
      UnknownOutcomeLockBlockedError
    );
    await assert.rejects(
      () =>
        apiFetch('/api/workforce/payments', {
          method: 'POST',
          idempotencyKey: 'NONCE-NEW-W',
          body: JSON.stringify({ amount: 500 }),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 0);
  });

  await runCase(24, 'Group D', 'Mutation with OMITTED explicit lockScope is STILL locked & enforced automatically', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ detail: { message: 'Gateway timeout' } }, 504);
    }) as typeof fetch;

    // Notice: NO lockScope passed at all!
    await assert.rejects(
      () =>
        apiRequest('/api/purchasing/bills', {
          method: 'POST',
          idempotencyKey: 'NONCE-OMIT-1',
          body: JSON.stringify({ supplier_id: 'SUP-1', total: 8000 }),
        }),
      (err: unknown) =>
        err instanceof ApiOutcomeUnknownError && err.scopeKey === 'purchasing_view'
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('purchasing_view'), true, 'Omitting lockScope MUST still persist scope lock');

    // Subsequent call ALSO omitting lockScope MUST be blocked before fetch!
    await assert.rejects(
      () =>
        apiRequest('/api/purchasing/payments', {
          method: 'POST',
          idempotencyKey: 'NONCE-OMIT-NEW',
          body: JSON.stringify({ supplier_id: 'SUP-1', amount: 8000 }),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 1, 'Omitting lockScope MUST NOT bypass active lock');
  });

  await runCase(25, 'Group D', 'Unknown or ambiguous mutation endpoint fails closed with AMBIGUOUS_TRANSACTION_SCOPE (0 fetch calls)', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    await assert.rejects(
      () =>
        apiRequest('/api/unmapped-rogue/mutation', {
          method: 'POST',
          idempotencyKey: 'NONCE-AMB-1',
          body: JSON.stringify({ x: 1 }),
        }),
      (err: unknown) =>
        err instanceof UnknownOutcomeLockBlockedError &&
        err.errorCode === 'AMBIGUOUS_TRANSACTION_SCOPE'
    );
    await assert.rejects(
      () =>
        apiFetch('/api/mystery/endpoint', {
          method: 'DELETE',
          idempotencyKey: 'NONCE-AMB-2',
        }),
      (err: unknown) =>
        err instanceof UnknownOutcomeLockBlockedError &&
        err.errorCode === 'AMBIGUOUS_TRANSACTION_SCOPE'
    );
    assert.throws(
      () => resolveMutationTransactionScope('/api/sales', '   '),
      (err: unknown) =>
        err instanceof UnknownOutcomeLockBlockedError &&
        err.errorCode === 'AMBIGUOUS_TRANSACTION_SCOPE'
    );
    assert.equal(fetchCalls, 0, 'Unknown/ambiguous endpoints MUST fail closed with 0 fetch calls');
  });

  await runCase(26, 'Group D', 'Blocked mutations across all failure modes cause ZERO network calls', async () => {
    const id = computeTransactionIdentityFingerprint({
      method: 'POST',
      path: '/api/sales',
      payload: { amount: 1000 },
    });
    persistUnknownOutcome(
      'sales_view',
      { nonce: 'NONCE-ZERO-1', message: 'Locked' },
      { amount: 1000 },
      { method: id.method, path: id.normalizedPath, transactionFingerprint: id.transactionFingerprint }
    );

    let fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls++;
      return jsonResponse({ ok: true });
    }) as typeof fetch;

    // 1. Fresh nonce
    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'POST', idempotencyKey: 'FRESH', body: JSON.stringify({ amount: 1000 }) }),
      UnknownOutcomeLockBlockedError
    );
    // 2. Method mismatch
    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'PUT', idempotencyKey: 'NONCE-ZERO-1', body: JSON.stringify({ amount: 1000 }) }),
      PayloadMismatchError
    );
    // 3. Endpoint mismatch
    await assert.rejects(
      () => apiRequest('/api/sales/orders', { method: 'POST', idempotencyKey: 'NONCE-ZERO-1', body: JSON.stringify({ amount: 1000 }) }),
      PayloadMismatchError
    );
    // 4. Payload mismatch
    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'POST', idempotencyKey: 'NONCE-ZERO-1', body: JSON.stringify({ amount: 2000 }) }),
      PayloadMismatchError
    );
    // 5. Unverified retry
    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'POST', idempotencyKey: 'NONCE-ZERO-1', requireVerifiedRetry: true, body: JSON.stringify({ amount: 1000 }) }),
      UnknownOutcomeLockBlockedError
    );
    // 6. Ambiguous endpoint
    await assert.rejects(
      () => apiRequest('/api/unknown/x', { method: 'POST', idempotencyKey: 'ANY', body: JSON.stringify({ a: 1 }) }),
      UnknownOutcomeLockBlockedError
    );

    assert.equal(fetchCalls, 0, 'Every single blocked mutation MUST fire ZERO fetch calls');
  });

  await runCase(27, 'Group D', 'GET status checks & legitimate GET reads remain available while mutation scope is locked', async () => {
    persistUnknownOutcome('sales_view', { nonce: 'NONCE-GET-OK', message: 'Locked' }, { amount: 500 });

    const calledUrls: string[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      calledUrls.push(url);
      if (url.includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('NONCE-GET-OK', 'IN_PROGRESS'));
      }
      return jsonResponse({ items: ['S-1'] });
    }) as typeof fetch;

    const readRes = await apiRequest<{ items: string[] }>('/api/sales', { method: 'GET' });
    assert.deepEqual(readRes.items, ['S-1']);

    const statusRes = await checkV2TransactionStatus('NONCE-GET-OK');
    assert.equal(statusRes.status, 'IN_PROGRESS');
    assert.equal(calledUrls.length, 2);
    assert.equal(isScopeLocked('sales_view'), true, 'IN_PROGRESS status must keep lock active');
  });

  await runCase(28, 'Group D', 'Identical authorized recovery succeeds and clears lock', async () => {
    let phase: 'fail' | 'status' | 'ok' = 'fail';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('NONCE-D28', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (phase === 'fail') {
        throw new TypeError('Failed to fetch');
      }
      return jsonResponse({ ok: true, id: 'OK-28' }, 200);
    }) as typeof fetch;

    const payload = { a: 1, b: 2 };
    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'POST', idempotencyKey: 'NONCE-D28', body: JSON.stringify(payload) }),
      ApiOutcomeUnknownError
    );
    assert.equal(isScopeLocked('sales_view'), true);

    phase = 'status';
    await checkV2TransactionStatus('NONCE-D28');

    phase = 'ok';
    const res = await apiRequest<{ ok: boolean }>('/api/sales', {
      method: 'POST',
      idempotencyKey: 'NONCE-D28',
      requireVerifiedRetry: true,
      body: JSON.stringify({ b: 2, a: 1 }),
    });
    assert.equal(res.ok, true);
    assert.equal(isScopeLocked('sales_view'), false);
  });

  await runCase(29, 'Group D', 'Changed recovery payload blocked even after NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE (0 fetch calls)', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('NONCE-D29', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      return jsonResponse({ detail: { message: 'Timeout' } }, 504);
    }) as typeof fetch;

    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'POST', idempotencyKey: 'NONCE-D29', body: JSON.stringify({ amount: 500 }) }),
      ApiOutcomeUnknownError
    );
    await checkV2TransactionStatus('NONCE-D29');
    assert.equal(fetchCalls, 2);

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-D29',
          requireVerifiedRetry: true,
          body: JSON.stringify({ amount: 550 }),
        }),
      PayloadMismatchError
    );
    assert.equal(fetchCalls, 2);
  });

  await runCase(30, 'Group D', 'New nonce cannot bypass recovery lock even after NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE', async () => {
    let fetchCalls = 0;
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('NONCE-D30', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      return jsonResponse({ detail: { message: 'Timeout' } }, 504);
    }) as typeof fetch;

    await assert.rejects(
      () => apiRequest('/api/sales', { method: 'POST', idempotencyKey: 'NONCE-D30', body: JSON.stringify({ amount: 500 }) }),
      ApiOutcomeUnknownError
    );
    await checkV2TransactionStatus('NONCE-D30');
    assert.equal(fetchCalls, 2);

    await assert.rejects(
      () =>
        apiRequest('/api/sales', {
          method: 'POST',
          idempotencyKey: 'NONCE-D30-FRESH',
          body: JSON.stringify({ amount: 500 }),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 2);
  });

  // =========================================================================
  // TEST GROUP E — VIEW / API BEHAVIORAL INTEGRATION (TX-FINAL-F-05)
  // =========================================================================

  await runCase(31, 'Group E', 'Purchasing mutation paths (createSupplierBill, recordSupplierPayment, applySupplierAdvance)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('PUR-BILL-1', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ bill_id: 'BILL-01' }, 200);
    }) as typeof fetch;

    const billPayload = {
      supplier_id: 'SUP-1',
      bill_number: 'INV-100',
      bill_date: '2026-11-22',
      subtotal: 10000,
      tax_amount: 500,
      total_amount: 10500,
    };

    await assert.rejects(() => createSupplierBill(billPayload, 'PUR-BILL-1'), ApiOutcomeUnknownError);
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('purchasing_view'), true);

    // Fresh-nonce payment in purchasing_view blocked (0 network calls)
    await assert.rejects(
      () =>
        recordSupplierPayment(
          { supplier_id: 'SUP-1', payment_date: '2026-11-22', amount: 10500, payment_mode: 'BANK' },
          'PUR-PAY-NEW'
        ),
      UnknownOutcomeLockBlockedError
    );
    // Same-nonce cross-endpoint reuse on applySupplierAdvance blocked (ENDPOINT_MISMATCH, 0 network calls)
    await assert.rejects(
      () => applySupplierAdvance('PAY-1', { bill_id: 'BILL-01', amount: 1000 }, 'PUR-BILL-1'),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    // Modified bill amount blocked (PAYLOAD_MISMATCH, 0 network calls)
    await assert.rejects(
      () => createSupplierBill({ ...billPayload, total_amount: 10600 }, 'PUR-BILL-1'),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'PAYLOAD_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    // Status verify & exact identical retry succeeds and clears lock
    mode = 'status';
    await checkV2TransactionStatus('PUR-BILL-1');
    mode = 'ok';
    const created = await createSupplierBill(billPayload, 'PUR-BILL-1');
    assert.equal((created as any).bill_id, 'BILL-01');
    assert.equal(fetchCalls, 3);
    assert.equal(isScopeLocked('purchasing_view'), false);
  });

  await runCase(32, 'Group E', 'Production packaging recovery (/api/production/packaging/{id}/recover)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'wrong_status' | 'good_status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(
          mode === 'wrong_status'
            ? mockStatusBody('PKG-OTHER-NONCE', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE')
            : mockStatusBody('PKG-REC-1', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE')
        );
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ ok: true, recovered_id: 'PKG-101' }, 200);
    }) as typeof fetch;

    const recoverBody = { recovery_reason: 'Mismatch reconciliation', resolved_by: 'Owner' };
    await assert.rejects(
      () =>
        apiRequest('/api/production/packaging/PKG-101/recover', {
          method: 'POST',
          idempotencyKey: 'PKG-REC-1',
          body: JSON.stringify(recoverBody),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('production_view'), true);

    // Same nonce directed at DIFFERENT packaging ID -> ENDPOINT_MISMATCH (0 fetch calls)
    await assert.rejects(
      () =>
        apiRequest('/api/production/packaging/PKG-102/recover', {
          method: 'POST',
          idempotencyKey: 'PKG-REC-1',
          body: JSON.stringify(recoverBody),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    // Wrong status nonce rejected & does NOT authorize retry
    mode = 'wrong_status';
    await assert.rejects(() => checkV2TransactionStatus('PKG-REC-1'), StatusResponseValidationError);
    assert.equal(fetchCalls, 2);

    await assert.rejects(
      () =>
        apiRequest('/api/production/packaging/PKG-101/recover', {
          method: 'POST',
          idempotencyKey: 'PKG-REC-1',
          requireVerifiedRetry: true,
          body: JSON.stringify(recoverBody),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 2);

    // Valid status -> identical recovery succeeds & unlocks
    mode = 'good_status';
    await checkV2TransactionStatus('PKG-REC-1');
    mode = 'ok';
    const recRes = await apiRequest<{ ok: boolean }>('/api/production/packaging/PKG-101/recover', {
      method: 'POST',
      idempotencyKey: 'PKG-REC-1',
      requireVerifiedRetry: true,
      body: JSON.stringify(recoverBody),
    });
    assert.equal(recRes.ok, true);
    assert.equal(isScopeLocked('production_view'), false);
  });

  await runCase(33, 'Group E', 'Production mutation paths (recordMillingBatch, receiveRawMaterial, /api/production/batches)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('MILL-1', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ ok: true, milling_id: 'ML-1' }, 200);
    }) as typeof fetch;

    const millPayload = {
      raw_material_id: 'RM-DAL',
      input_kg: 100,
      output_product_id: 'FG-BESAN',
      output_kg: 92,
      milling_date: '2026-11-22',
    };

    await assert.rejects(() => recordMillingBatch(millPayload, 'MILL-1'), ApiOutcomeUnknownError);
    assert.equal(fetchCalls, 1);

    // Survives reload and blocks receiveRawMaterial & new batch creation with 0 fetch calls
    simulatePageReload();
    await assert.rejects(
      () =>
        receiveRawMaterial(
          { raw_material_id: 'RM-DAL', quantity_kg: 50, rate_per_kg: 80 },
          'RM-NEW-1'
        ),
      UnknownOutcomeLockBlockedError
    );
    await assert.rejects(
      () =>
        apiRequest('/api/production/batches', {
          method: 'POST',
          idempotencyKey: 'BATCH-NEW-1',
          body: JSON.stringify({ recipe_id: 'RCP-1', batch_kg: 25 }),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 1);

    mode = 'status';
    await checkV2TransactionStatus('MILL-1');
    mode = 'ok';
    const res = await recordMillingBatch(millPayload, 'MILL-1');
    assert.equal((res as any).ok, true);
    assert.equal(isScopeLocked('production_view'), false);
  });

  await runCase(34, 'Group E', 'Sales mutations (POST /api/sales, createSalesOrder, recordSalePaymentApi)', async () => {
    let fetchCalls = 0;
    let mode: 'drop' | 'status' | 'ok' = 'drop';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('SALE-E34', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === 'drop') throw new TypeError('Failed to fetch');
      return jsonResponse({ sale_id: 'SL-E34' }, 200);
    }) as typeof fetch;

    const orderPayload = { customer_id: 'CUS-34', items: [{ product_id: 'P-1', qty: 4, rate: 250 }] };
    await assert.rejects(() => createSalesOrder(orderPayload, 'SALE-E34'), ApiOutcomeUnknownError);
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('sales_view'), true);

    // Blocks recordSalePaymentApi with fresh nonce AND with reused nonce (ENDPOINT_MISMATCH)
    await assert.rejects(
      () => recordSalePaymentApi('SL-1', { amount: 1000, payment_mode: 'CASH' }, 'SALE-PAY-FRESH'),
      UnknownOutcomeLockBlockedError
    );
    await assert.rejects(
      () => recordSalePaymentApi('SL-1', { amount: 1000, payment_mode: 'CASH' }, 'SALE-E34'),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    mode = 'status';
    await checkV2TransactionStatus('SALE-E34');
    mode = 'ok';
    const res = await createSalesOrder(orderPayload, 'SALE-E34');
    assert.equal(res.sale_id, 'SL-E34');
    assert.equal(isScopeLocked('sales_view'), false);
  });

  await runCase(35, 'Group E', 'Accounting mutations (executeReconciliation query-flag binding, reverseJournalVoucherApi, closeAccountingPeriod)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('ACC-REC-1', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ status: 'OK' }, 200);
    }) as typeof fetch;

    // executeReconciliation posts to /api/accounting/reconcile?dry_run=false&confirm_live_backfill=true
    await assert.rejects(
      () => executeReconciliation(false, true, 'ACC-REC-1'),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('accounting_view'), true);

    // Switching query flag dry_run=true with same nonce -> ENDPOINT_MISMATCH (0 fetch calls)
    await assert.rejects(
      () => executeReconciliation(true, true, 'ACC-REC-1'),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    // Fresh-nonce voucher reversal & period close blocked (0 fetch calls)
    await assert.rejects(
      () => reverseJournalVoucherApi('JV-1', 'Correction', 'ACC-REV-NEW'),
      UnknownOutcomeLockBlockedError
    );
    await assert.rejects(
      () => closeAccountingPeriod('PER-2026-11', 'ACC-CLS-NEW'),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 1);

    mode = 'status';
    await checkV2TransactionStatus('ACC-REC-1');
    mode = 'ok';
    const res = await executeReconciliation(false, true, 'ACC-REC-1');
    assert.equal((res as any).status, 'OK');
    assert.equal(isScopeLocked('accounting_view'), false);
  });

  await runCase(36, 'Group E', 'Closing mutations (POST /api/closing & PUT /api/closing/{id}/review)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('CLS-E36', 'CONFIRMED_RECORDED'));
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ ok: true }, 200);
    }) as typeof fetch;

    const closingPayload = { closing_date: '2026-11-22', cash_collected: 45200, expenses_total: 1200 };
    await assert.rejects(
      () =>
        apiRequest('/api/closing', {
          method: 'POST',
          idempotencyKey: 'CLS-E36',
          body: JSON.stringify(closingPayload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('closing_view'), true);

    // Changing method POST -> PUT on /api/closing blocked with 0 fetch calls
    await assert.rejects(
      () =>
        apiRequest('/api/closing', {
          method: 'PUT',
          idempotencyKey: 'CLS-E36',
          body: JSON.stringify(closingPayload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'METHOD_MISMATCH'
    );
    // Changing cash_collected blocked with 0 fetch calls
    await assert.rejects(
      () =>
        apiRequest('/api/closing', {
          method: 'POST',
          idempotencyKey: 'CLS-E36',
          body: JSON.stringify({ ...closingPayload, cash_collected: 45000 }),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'PAYLOAD_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    // Authoritative CONFIRMED_RECORDED unlocks closing_view
    mode = 'status';
    const st = await checkV2TransactionStatus('CLS-E36');
    const cleared = resolveAndClearUnknownOutcome('closing_view', {
      status: st.status,
      nonce: 'CLS-E36',
      statusResponse: st,
    });
    assert.equal(cleared.cleared, true);
    assert.equal(isScopeLocked('closing_view'), false);
  });

  await runCase(37, 'Group E', 'Workforce mutations via apiFetch (/api/workforce/payments, /payroll/calculate, /payroll/{id}/approve)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('WF-E37', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ ok: true, payment_id: 'WP-37' }, 200);
    }) as typeof fetch;

    const wfPayload = { employee_id: 'EMP-7', amount: 18500, payment_mode: 'NEFT' };
    // Omitting lockScope intentionally -> TX-FINAL-F-04 resolves workforce_view automatically
    await assert.rejects(
      () =>
        apiFetch('/api/workforce/payments', {
          method: 'POST',
          idempotencyKey: 'WF-E37',
          body: JSON.stringify(wfPayload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('workforce_view'), true);

    simulatePageReload();

    // Another workforce mutation (payroll calculate) blocked with 0 fetch calls
    await assert.rejects(
      () =>
        apiFetch('/api/workforce/payroll/calculate', {
          method: 'POST',
          idempotencyKey: 'WF-CALC-NEW',
          body: JSON.stringify({ month: '2026-11' }),
        }),
      UnknownOutcomeLockBlockedError
    );
    // Same nonce pointed at payroll approve blocked with ENDPOINT_MISMATCH
    await assert.rejects(
      () =>
        apiFetch('/api/workforce/payroll/PR-9/approve', {
          method: 'POST',
          idempotencyKey: 'WF-E37',
          body: JSON.stringify(wfPayload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    assert.equal(fetchCalls, 1);

    mode = 'status';
    await checkV2TransactionStatus('WF-E37');
    mode = 'ok';
    const okRes = await apiFetch('/api/workforce/payments', {
      method: 'POST',
      idempotencyKey: 'WF-E37',
      requireVerifiedRetry: true,
      body: JSON.stringify(wfPayload),
    });
    assert.equal(okRes.status, 200);
    assert.equal(isScopeLocked('workforce_view'), false);
  });

  await runCase(38, 'Group E', 'Salary mutations (/api/salary/calculate, /api/salary/{id}/approve, /api/salary/{id}/pay)', async () => {
    let fetchCalls = 0;
    let mode: 'drop' | 'status' | 'ok' = 'drop';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('SAL-E38', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === 'drop') throw new TypeError('NetworkError when attempting to fetch resource.');
      return jsonResponse({ ok: true, run_id: 'SAL-RUN-11' }, 200);
    }) as typeof fetch;

    const salPayload = { month: '2026-11', employee_id: 'EMP-12', incentive: 2500 };
    await assert.rejects(
      () =>
        apiRequest('/api/salary/calculate', {
          method: 'POST',
          idempotencyKey: 'SAL-E38',
          body: JSON.stringify(salPayload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('salary_view'), true);

    // Fresh-nonce pay action blocked (0 fetch calls)
    await assert.rejects(
      () =>
        apiRequest('/api/salary/SAL-1/pay', {
          method: 'PUT',
          idempotencyKey: 'SAL-PAY-FRESH',
          body: JSON.stringify({ paid: true }),
        }),
      UnknownOutcomeLockBlockedError
    );
    // Same nonce reused on approve endpoint blocked (METHOD_MISMATCH / ENDPOINT_MISMATCH, 0 fetch calls)
    await assert.rejects(
      () =>
        apiRequest('/api/salary/SAL-1/approve', {
          method: 'PUT',
          idempotencyKey: 'SAL-E38',
          body: JSON.stringify(salPayload),
        }),
      PayloadMismatchError
    );
    assert.equal(fetchCalls, 1);

    mode = 'status';
    await checkV2TransactionStatus('SAL-E38');
    mode = 'ok';
    const res = await apiRequest<{ ok: boolean }>('/api/salary/calculate', {
      method: 'POST',
      idempotencyKey: 'SAL-E38',
      requireVerifiedRetry: true,
      body: JSON.stringify(salPayload),
    });
    assert.equal(res.ok, true);
    assert.equal(isScopeLocked('salary_view'), false);
  });

  await runCase(39, 'Group E', 'Expenses mutations (/api/expenses, /api/expenses/{id}/approve, /api/expenses/{id}/reject)', async () => {
    let fetchCalls = 0;
    let mode: '504' | 'status' | 'ok' = '504';
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      fetchCalls++;
      if (String(input).includes('/api/v2/transactions/status/')) {
        return jsonResponse(mockStatusBody('EXP-E39', 'NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE'));
      }
      if (mode === '504') return jsonResponse({ detail: { message: 'Timeout' } }, 504);
      return jsonResponse({ ok: true, expense_id: 'EXP-39' }, 200);
    }) as typeof fetch;

    const expPayload = { category: 'FUEL', amount: 3400, description: 'Van diesel' };
    await assert.rejects(
      () =>
        apiRequest('/api/expenses/EXP-39/approve', {
          method: 'PUT',
          idempotencyKey: 'EXP-E39',
          body: JSON.stringify(expPayload),
        }),
      ApiOutcomeUnknownError
    );
    assert.equal(fetchCalls, 1);
    assert.equal(isScopeLocked('expenses_view'), true);

    // Switching approve -> reject with same unresolved nonce blocked (ENDPOINT_MISMATCH, 0 fetch calls)
    await assert.rejects(
      () =>
        apiRequest('/api/expenses/EXP-39/reject', {
          method: 'PUT',
          idempotencyKey: 'EXP-E39',
          body: JSON.stringify(expPayload),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'ENDPOINT_MISMATCH'
    );
    // Changing expense amount blocked (PAYLOAD_MISMATCH, 0 fetch calls)
    await assert.rejects(
      () =>
        apiRequest('/api/expenses/EXP-39/approve', {
          method: 'PUT',
          idempotencyKey: 'EXP-E39',
          body: JSON.stringify({ ...expPayload, amount: 3500 }),
        }),
      (err: unknown) => err instanceof PayloadMismatchError && err.mismatchType === 'PAYLOAD_MISMATCH'
    );
    // Submitting a brand-new expense with fresh nonce blocked (0 fetch calls)
    await assert.rejects(
      () =>
        apiRequest('/api/expenses', {
          method: 'POST',
          idempotencyKey: 'EXP-FRESH',
          body: JSON.stringify({ category: 'TOLL', amount: 150 }),
        }),
      UnknownOutcomeLockBlockedError
    );
    assert.equal(fetchCalls, 1);

    mode = 'status';
    await checkV2TransactionStatus('EXP-E39');
    mode = 'ok';
    const okRes = await apiRequest<{ ok: boolean }>('/api/expenses/EXP-39/approve', {
      method: 'PUT',
      idempotencyKey: 'EXP-E39',
      requireVerifiedRetry: true,
      body: JSON.stringify(expPayload),
    });
    assert.equal(okRes.ok, true);
    assert.equal(isScopeLocked('expenses_view'), false);
  });

  // -------------------------------------------------------------------------
  // Summary
  // -------------------------------------------------------------------------
  const passedCount = results.filter((r) => r.passed).length;
  const failedCount = results.filter((r) => !r.passed).length;
  console.log(`\n=== SUMMARY: ${passedCount}/${results.length} PASSED, ${failedCount} FAILED ===\n`);

  if (failedCount > 0) {
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Unhandled test runner failure:', err);
  process.exit(1);
});
