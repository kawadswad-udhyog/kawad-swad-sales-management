/**
 * Kawad Swad ERP — Mission 51B-1 Frontend Transaction Safety Test Suite
 *
 * Verifies:
 * 1. Synchronous in-flight mutation deduplication blocks double-clicks within the same tick.
 * 2. Mutating requests (POST/PUT/PATCH/DELETE) NEVER auto-retry via proxy fallback on network errors.
 * 3. Read-only GET requests preserve dual-path proxy fallback cleanly.
 * 4. Network drop / timeout on mutations throws ApiOutcomeUnknownError preserving the exact nonce.
 * 5. RECOVERY_REQUIRED errors are parsed as non-retryable and surfaced via extractUnknownOutcomeInfo.
 * 6. Static contract checks on UnknownOutcomeBanner.tsx (retry gated behind status check + cooldown)
 *    and StoreContext.tsx (no unverified optimistic mutation in toggleProductActive).
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

// Minimal browser globals stub for running api.ts cleanly under tsx/node
const storage = new Map<string, string>();
(globalThis as any).localStorage = {
  getItem: (k: string) => (storage.has(k) ? storage.get(k)! : null),
  setItem: (k: string, v: string) => storage.set(k, String(v)),
  removeItem: (k: string) => storage.delete(k),
  clear: () => storage.clear(),
};
(globalThis as any).window = {
  location: { origin: 'http://localhost:3000', hostname: 'localhost' },
  dispatchEvent: () => true,
};

import {
  apiRequest,
  ApiHttpError,
  ApiOutcomeUnknownError,
  extractUnknownOutcomeInfo,
  getInflightMutationCount,
  isRecoveryRequiredError,
  normalizeApiErrorPayload,
  setApiBaseUrl,
} from '../src/services/api.ts';

async function runTests() {
  let passed = 0;

  // Test 1: Synchronous in-flight mutation deduplication blocks double-click
  {
    setApiBaseUrl('');
    let fetchCalls = 0;
    let resolveFetch!: (value: any) => void;

    (globalThis as any).fetch = () => {
      fetchCalls += 1;
      return new Promise((resolve) => {
        resolveFetch = resolve;
      });
    };

    const p1 = apiRequest('/api/v2/finance/journals', {
      method: 'POST',
      body: JSON.stringify({ narration: 'Test', amount: 100 }),
      idempotencyKey: 'NONCE-FE-DBLCLICK-1',
    });

    assert.equal(getInflightMutationCount(), 1, 'Expected 1 in-flight mutation tracked');

    let dupErr: unknown = null;
    try {
      await apiRequest('/api/v2/finance/journals', {
        method: 'POST',
        body: JSON.stringify({ narration: 'Test', amount: 100 }),
        idempotencyKey: 'NONCE-FE-DBLCLICK-1',
      });
    } catch (err) {
      dupErr = err;
    }

    assert.ok(dupErr instanceof ApiHttpError, 'Duplicate click must throw ApiHttpError');
    assert.equal((dupErr as ApiHttpError).status, 409);
    assert.equal((dupErr as ApiHttpError).errorCode, 'CONCURRENT_DUPLICATE_REQUEST');
    assert.equal((dupErr as ApiHttpError).failureCategory, 'DUPLICATE_REQUEST');
    assert.equal(fetchCalls, 1, 'Duplicate click must NOT fire a second fetch()');

    // Finish first request cleanly
    resolveFetch({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () => JSON.stringify({ status: 'CONFIRMED', allocated_id: 'JV-000001' }),
    });
    const r1 = await p1;
    assert.deepEqual(r1, { status: 'CONFIRMED', allocated_id: 'JV-000001' });
    assert.equal(getInflightMutationCount(), 0, 'In-flight mutation map must clean up in finally');
    passed += 1;
  }

  // Test 2: Mutations NEVER auto-retry via proxy fallback on network drop; throw ApiOutcomeUnknownError preserving nonce
  {
    setApiBaseUrl('https://api.kawadswad.test');
    let fetchCalls = 0;
    (globalThis as any).fetch = async () => {
      fetchCalls += 1;
      throw new TypeError('Failed to fetch');
    };

    let caught: unknown = null;
    try {
      await apiRequest('/api/sales', {
        method: 'POST',
        body: JSON.stringify({ items: [{ product_id: 'PROD-1', qty: 1 }] }),
        idempotencyKey: 'NONCE-FE-NORETRY-1',
      });
    } catch (err) {
      caught = err;
    }

    assert.equal(fetchCalls, 1, 'Mutating POST must NEVER auto-retry via proxy fallback');
    assert.ok(
      caught instanceof ApiOutcomeUnknownError || caught instanceof Error,
      'Network failure must surface an explicit error'
    );
    // Simulate same-origin network drop -> must throw ApiOutcomeUnknownError with preserved nonce
    setApiBaseUrl('');
    fetchCalls = 0;
    let sameOriginErr: unknown = null;
    try {
      await apiRequest('/api/sales', {
        method: 'POST',
        body: JSON.stringify({ items: [{ product_id: 'PROD-1', qty: 1 }] }),
        idempotencyKey: 'NONCE-FE-UNKNOWN-DROP',
      });
    } catch (err) {
      sameOriginErr = err;
    }
    assert.equal(fetchCalls, 1);
    assert.ok(sameOriginErr instanceof ApiOutcomeUnknownError, 'Dropped mutation must throw ApiOutcomeUnknownError');
    assert.equal((sameOriginErr as ApiOutcomeUnknownError).nonce, 'NONCE-FE-UNKNOWN-DROP');
    passed += 1;
  }

  // Test 3: Read-only GET requests DO still support dual-path proxy fallback
  {
    setApiBaseUrl('https://api.kawadswad.test');
    const urlsCalled: string[] = [];
    (globalThis as any).fetch = async (url: string) => {
      urlsCalled.push(url);
      if (urlsCalled.length === 1) {
        throw new TypeError('Failed to fetch');
      }
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => JSON.stringify({ ok: true }),
      };
    };

    const res = await apiRequest('/api/products', { method: 'GET' });
    assert.deepEqual(res, { ok: true });
    assert.equal(urlsCalled.length, 2, 'Read-only GET should fall back to proxy path');
    assert.equal(urlsCalled[1], '/api/products');
    passed += 1;
  }

  // Test 4: RECOVERY_REQUIRED normalized as non-retryable & extracted into UnknownOutcomeState
  {
    const parsed = normalizeApiErrorPayload(
      {
        detail: {
          status: 'RECOVERY_REQUIRED',
          transaction_id: 'TXN-REC123',
          transaction_state: 'RECOVERY_REQUIRED',
          failure_category: 'RECOVERY_REQUIRED',
          error_code: 'PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED',
          nonce: 'NONCE-FE-REC-1',
          correlation_id: 'CORR-REC-1',
          retryable: true, // Even if a buggy caller sent true, normalizer forces false!
          message: 'Partial write detected; Owner reconciliation required.',
        },
      },
      409
    );
    assert.equal(parsed.retryable, false);
    assert.equal(parsed.transactionState, 'RECOVERY_REQUIRED');
    assert.equal(parsed.failureCategory, 'RECOVERY_REQUIRED');
    assert.equal(parsed.nonce, 'NONCE-FE-REC-1');

    const httpErr = new ApiHttpError(409, parsed.errorMsg, 'HTTP_ERROR', '/api/sales', false, {
      errorCode: parsed.errorCode,
      correlationId: parsed.correlationId,
      retryable: parsed.retryable,
      transactionId: parsed.transactionId,
      transactionState: parsed.transactionState,
      failureCategory: parsed.failureCategory,
      nonce: parsed.nonce,
    });
    assert.equal(isRecoveryRequiredError(httpErr), true);

    const outcome = extractUnknownOutcomeInfo(httpErr, 'FALLBACK', 'Create Sale');
    assert.ok(outcome !== null);
    assert.equal(outcome!.recoveryRequired, true);
    assert.equal(outcome!.transactionState, 'RECOVERY_REQUIRED');
    assert.equal(outcome!.nonce, 'NONCE-FE-REC-1');
    assert.equal(outcome!.transactionId, 'TXN-REC123');
    passed += 1;
  }

  // Test 5: Static UI contracts on UnknownOutcomeBanner.tsx and StoreContext.tsx
  {
    const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
    const bannerSrc = fs.readFileSync(
      path.join(rootDir, 'src/components/common/UnknownOutcomeBanner.tsx'),
      'utf-8'
    );
    assert.ok(bannerSrc.includes('STATUS_CHECK_COOLDOWN_MS'), 'Banner must enforce status check cooldown');
    assert.ok(bannerSrc.includes('disabled={!isSafeRetry}'), 'Retry button must be disabled until status verified safe');
    assert.ok(bannerSrc.includes("statusResult?.status === 'RECOVERY_REQUIRED'"), 'Banner must handle RECOVERY_REQUIRED');
    assert.ok(bannerSrc.includes("statusResult?.status === 'RECONCILED'"), 'Banner must handle RECONCILED');
    assert.ok(bannerSrc.includes('!isRecoveryRequired'), 'Banner must block retry when RECOVERY_REQUIRED');

    const storeSrc = fs.readFileSync(path.join(rootDir, 'src/context/StoreContext.tsx'), 'utf-8');
    const toggleIdx = storeSrc.indexOf('const toggleProductActive');
    const toggleBlock = storeSrc.slice(toggleIdx, toggleIdx + 400);
    assert.ok(
      !toggleBlock.includes('setProducts('),
      'toggleProductActive must NOT optimistically mutate setProducts before server confirmation'
    );
    passed += 1;
  }

  console.log(`Mission 51B-1 Frontend Transaction Safety Tests: ${passed}/5 PASSED`);
}

runTests().catch((err) => {
  console.error('Mission 51B-1 Frontend Transaction Safety Tests FAILED:', err);
  process.exit(1);
});
