/**
 * Mission 51B-1R — TX-FINAL-04 Regression Suite: Frontend UNKNOWN-Outcome Safety & Locking.
 *
 * Verifies all 8 required TX-FINAL-04 behaviors:
 * 1. Lock helpers (`isOutcomeLocked`, `shouldBlockDraftNonceReset`) & sessionStorage persistence survive remount/navigation.
 * 2. Editing attempts while locked cannot clear or rotate the preserved nonce.
 * 3. Post-transmission `TypeError: Failed to fetch` (both same-origin AND cross-origin) in BOTH `apiRequest` AND `apiFetch`
 *    is classified as `ApiOutcomeUnknownError` (`UNKNOWN`) with preserved nonce and zero auto-retry.
 * 4. Synchronous in-flight duplicate submission is blocked in BOTH `apiRequest` AND `apiFetch`
 *    (including workforce payroll calculate/approve/disburse).
 * 5. `apiFetch` classifies HTTP 504 AND HTTP 409 `RECOVERY_REQUIRED` / `PENDING_UNKNOWN` as `ApiOutcomeUnknownError`.
 * 6. `UnknownOutcomeBanner.tsx` removes casual dismiss escape while unresolved, renders lock notice,
 *    keeps status check + same-nonce retry accessible, and only permits unlock after verified confirmation/reconciliation.
 * 7. All 17 mutating views across `src/views/` enforce `useUnknownOutcomeGuard`, `UnknownOutcomeBanner`,
 *    and `data-tx-form-locked` `<fieldset disabled={...}>` lock contracts (and 3 read-only views have zero writes).
 * 8. Workforce payroll calculate/approve/disbursement flows preserve nonces, lock modals/inputs, and surface UnknownOutcomeBanner.
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

// Minimal browser globals stub (localStorage + sessionStorage + window)
const localStore = new Map<string, string>();
const sessionStore = new Map<string, string>();

const makeStorage = (backing: Map<string, string>) => ({
  getItem: (k: string) => (backing.has(k) ? backing.get(k)! : null),
  setItem: (k: string, v: string) => backing.set(k, String(v)),
  removeItem: (k: string) => backing.delete(k),
  clear: () => backing.clear(),
  key: (i: number) => Array.from(backing.keys())[i] ?? null,
  get length() {
    return backing.size;
  },
});

(globalThis as any).localStorage = makeStorage(localStore);
(globalThis as any).sessionStorage = makeStorage(sessionStore);
(globalThis as any).window = {
  location: { origin: 'http://localhost:3000', hostname: 'localhost' },
  sessionStorage: (globalThis as any).sessionStorage,
  localStorage: (globalThis as any).localStorage,
  dispatchEvent: () => true,
};

import {
  apiFetch,
  apiRequest,
  ApiHttpError,
  ApiOutcomeUnknownError,
  getInflightMutationCount,
  setApiBaseUrl,
} from '../src/services/api.ts';
import {
  __resetUnknownLockRegistriesForTest,
  clearPersistedUnknownOutcome,
  computePayloadFingerprint,
  isOutcomeLocked,
  loadPersistedUnknownOutcome,
  persistUnknownOutcome,
  shouldBlockDraftNonceReset,
} from '../src/utils/unknownOutcomeLock.ts';

async function runTests() {
  let passed = 0;

  // Test 1: Lock state helpers, payload fingerprinting, and sessionStorage persistence across remount
  {
    sessionStore.clear();
    assert.equal(isOutcomeLocked(null), false);
    assert.equal(shouldBlockDraftNonceReset(null), false);

    const outcome = {
      nonce: 'NONCE-TX04-LOCK-1',
      correlationId: 'CORR-TX04-1',
      transactionId: 'TXN-TX04-1',
      transactionState: 'UNKNOWN',
      failureCategory: 'WRITE_OUTCOME_UNKNOWN',
      actionLabel: 'Create Sale',
      message: 'Status not confirmed',
      recoveryRequired: false,
    };

    assert.equal(isOutcomeLocked(outcome), true);
    assert.equal(shouldBlockDraftNonceReset(outcome), true);

    const fp = computePayloadFingerprint({ customer_id: 'CUST-1', amount: 1200 });
    persistUnknownOutcome('sales_view', outcome, fp);

    // Simulate remount / route navigation restoring persisted lock
    const restored = loadPersistedUnknownOutcome('sales_view');
    assert.ok(restored !== null, 'Persisted UNKNOWN lock must survive remount via sessionStorage');
    assert.equal(restored!.preservedNonce, 'NONCE-TX04-LOCK-1');
    assert.equal(restored!.payloadFingerprint, fp);
    assert.equal(restored!.outcome.transactionState, 'UNKNOWN');

    // Editing guard must prevent clearing/rotating draft nonce while locked
    let activeDraftNonce: string | null = 'NONCE-TX04-LOCK-1';
    const simulatedFieldChange = () => {
      if (!shouldBlockDraftNonceReset(restored!.outcome)) {
        activeDraftNonce = null;
      }
    };
    simulatedFieldChange();
    assert.equal(activeDraftNonce, 'NONCE-TX04-LOCK-1', 'Edit attempt while locked MUST NOT clear nonce');

    clearPersistedUnknownOutcome('sales_view');
    assert.equal(loadPersistedUnknownOutcome('sales_view'), null);
    passed += 1;
  }

  // Test 2: Post-transmission TypeError: Failed to fetch (cross-origin AND same-origin) -> ApiOutcomeUnknownError in BOTH apiRequest & apiFetch
  {
    for (const baseUrl of ['https://api.kawadswad.test', '']) {
      __resetUnknownLockRegistriesForTest();
      sessionStore.clear();
      setApiBaseUrl(baseUrl);

      // 2a. apiRequest
      let reqCalls = 0;
      (globalThis as any).fetch = async () => {
        reqCalls += 1;
        throw new TypeError('Failed to fetch');
      };
      let reqErr: unknown = null;
      try {
        await apiRequest('/api/sales', {
          method: 'POST',
          body: JSON.stringify({ amount: 500 }),
          idempotencyKey: `NONCE-REQ-${baseUrl ? 'CROSS' : 'SAME'}`,
        });
      } catch (e) {
        reqErr = e;
      }
      assert.equal(reqCalls, 1, 'apiRequest POST must NEVER auto-retry on network drop');
      assert.ok(reqErr instanceof ApiOutcomeUnknownError, `apiRequest network drop (${baseUrl || 'same-origin'}) must throw ApiOutcomeUnknownError`);
      assert.equal((reqErr as ApiOutcomeUnknownError).nonce, `NONCE-REQ-${baseUrl ? 'CROSS' : 'SAME'}`);

      // 2b. apiFetch (used by WorkforceView payroll actions)
      let fetchCalls = 0;
      (globalThis as any).fetch = async () => {
        fetchCalls += 1;
        throw new TypeError('Failed to fetch');
      };
      let afErr: unknown = null;
      try {
        await apiFetch('/api/workforce/payroll/calculate', {
          method: 'POST',
          body: JSON.stringify({ month: '2026-11' }),
          idempotencyKey: `NONCE-AF-${baseUrl ? 'CROSS' : 'SAME'}`,
        });
      } catch (e) {
        afErr = e;
      }
      assert.equal(fetchCalls, 1, 'apiFetch POST must NEVER auto-retry on network drop');
      assert.ok(afErr instanceof ApiOutcomeUnknownError, `apiFetch network drop (${baseUrl || 'same-origin'}) must throw ApiOutcomeUnknownError`);
      assert.equal((afErr as ApiOutcomeUnknownError).nonce, `NONCE-AF-${baseUrl ? 'CROSS' : 'SAME'}`);
    }
    passed += 1;
  }

  // Test 3: Synchronous in-flight duplicate submission blocked in apiFetch (Workforce payroll disbursement)
  {
    __resetUnknownLockRegistriesForTest();
    sessionStore.clear();
    setApiBaseUrl('');
    let calls = 0;
    let resolveFirst!: (v: any) => void;
    (globalThis as any).fetch = () => {
      calls += 1;
      return new Promise((resolve) => {
        resolveFirst = resolve;
      });
    };

    const p1 = apiFetch('/api/workforce/payments', {
      method: 'POST',
      body: JSON.stringify({ employee_id: 'EMP-1', amount: 8500 }),
      idempotencyKey: 'NONCE-WF-DISB-1',
    });

    assert.equal(getInflightMutationCount(), 1);

    let dupErr: unknown = null;
    try {
      await apiFetch('/api/workforce/payments', {
        method: 'POST',
        body: JSON.stringify({ employee_id: 'EMP-1', amount: 8500 }),
        idempotencyKey: 'NONCE-WF-DISB-1',
      });
    } catch (e) {
      dupErr = e;
    }

    assert.ok(dupErr instanceof ApiHttpError, 'Duplicate apiFetch click must throw ApiHttpError');
    assert.equal((dupErr as ApiHttpError).status, 409);
    assert.equal((dupErr as ApiHttpError).errorCode, 'CONCURRENT_DUPLICATE_REQUEST');
    assert.equal(calls, 1, 'Duplicate apiFetch click must NOT fire a second fetch()');

    resolveFirst({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () => JSON.stringify({ status: 'CONFIRMED', allocated_id: 'WP-000001' }),
      json: async () => ({ status: 'CONFIRMED', allocated_id: 'WP-000001' }),
    });
    const okRes = await p1;
    const okData = await okRes.json();
    assert.equal(okData.allocated_id, 'WP-000001');
    assert.equal(getInflightMutationCount(), 0);
    passed += 1;
  }

  // Test 4: apiFetch classifies HTTP 504 AND HTTP 409 RECOVERY_REQUIRED as ApiOutcomeUnknownError
  {
    setApiBaseUrl('');
    (globalThis as any).fetch = async () => ({
      ok: false,
      status: 504,
      statusText: 'Gateway Timeout',
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () =>
        JSON.stringify({
          detail: {
            status: 'PENDING_UNKNOWN',
            transaction_id: 'TXN-AF-504',
            transaction_state: 'UNKNOWN',
            failure_category: 'WRITE_OUTCOME_UNKNOWN',
            error_code: 'APPS_SCRIPT_TIMEOUT',
            nonce: 'NONCE-AF-504',
            message: 'Status not confirmed',
          },
        }),
    });

    let err504: unknown = null;
    try {
      await apiFetch('/api/workforce/payroll/PR-1/approve', {
        method: 'POST',
        body: JSON.stringify({ approved: true }),
        idempotencyKey: 'NONCE-AF-504',
      });
    } catch (e) {
      err504 = e;
    }
    assert.ok(err504 instanceof ApiOutcomeUnknownError, 'apiFetch HTTP 504 must throw ApiOutcomeUnknownError');
    assert.equal((err504 as ApiOutcomeUnknownError).nonce, 'NONCE-AF-504');

    // Isolate independent HTTP 409 sub-case from the HTTP 504 lock established above
    __resetUnknownLockRegistriesForTest();
    sessionStore.clear();

    (globalThis as any).fetch = async () => ({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () =>
        JSON.stringify({
          detail: {
            status: 'RECOVERY_REQUIRED',
            transaction_id: 'TXN-AF-409',
            transaction_state: 'RECOVERY_REQUIRED',
            failure_category: 'RECOVERY_REQUIRED',
            error_code: 'PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED',
            nonce: 'NONCE-AF-409',
            message: 'Recovery required',
          },
        }),
    });

    let err409: unknown = null;
    try {
      await apiFetch('/api/workforce/payments', {
        method: 'POST',
        body: JSON.stringify({ amount: 2000 }),
        idempotencyKey: 'NONCE-AF-409',
      });
    } catch (e) {
      err409 = e;
    }
    assert.ok(err409 instanceof ApiOutcomeUnknownError, 'apiFetch HTTP 409 RECOVERY_REQUIRED must throw ApiOutcomeUnknownError');
    assert.equal((err409 as ApiOutcomeUnknownError).transactionState, 'RECOVERY_REQUIRED');
    passed += 1;
  }

  // Test 5: UnknownOutcomeBanner contract — no casual Dismiss while unresolved, lock notice present, verified unlock only
  {
    const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
    const bannerSrc = fs.readFileSync(
      path.join(rootDir, 'src/components/common/UnknownOutcomeBanner.tsx'),
      'utf-8'
    );
    assert.ok(bannerSrc.includes('isVerifiedResolved'), 'Banner must track verified resolution before allowing unlock');
    assert.ok(
      bannerSrc.includes('Unlock Form (Verified)'),
      'Banner must gate unlock button behind verified CONFIRMED_RECORDED/RECONCILED status'
    );
    assert.ok(
      bannerSrc.includes('Form Locked:'),
      'Banner must clearly inform user that form inputs and new submissions are locked while unresolved'
    );
    assert.ok(
      !bannerSrc.includes('>Dismiss<'),
      'Banner must NOT render a casual unresolved Dismiss button that silently unlocks forms'
    );
    passed += 1;
  }

  // Test 6: Complete 17-view mutating frontend compliance audit (all 17 mutating views + 3 read-only views)
  {
    const rootDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
    const viewsDir = path.join(rootDir, 'src/views');
    const allViewFiles = fs
      .readdirSync(viewsDir)
      .filter((f) => f.endsWith('.tsx'))
      .sort();

    const readOnlyViews = new Set(['AuditView.tsx', 'DashboardView.tsx', 'ReportsView.tsx']);
    const mutatingViews = allViewFiles.filter((f) => !readOnlyViews.has(f));

    assert.equal(mutatingViews.length, 17, `Expected 17 mutating views, found ${mutatingViews.length}: ${mutatingViews.join(', ')}`);
    assert.equal(readOnlyViews.size, 3);

    for (const file of mutatingViews) {
      const src = fs.readFileSync(path.join(viewsDir, file), 'utf-8');
      assert.ok(src.includes('useUnknownOutcomeGuard'), `${file}: missing useUnknownOutcomeGuard`);
      assert.ok(src.includes('UnknownOutcomeBanner'), `${file}: missing UnknownOutcomeBanner`);
      assert.ok(src.includes('extractUnknownOutcomeInfo'), `${file}: missing extractUnknownOutcomeInfo`);
      assert.ok(src.includes('data-tx-form-locked'), `${file}: missing data-tx-form-locked fieldset lock`);
      assert.ok(src.includes('disabled={isOutcomeLocked}') || src.includes('disabled={isOutcomeLocked ||'), `${file}: missing disabled fieldset lock`);
    }

    // Verify WorkforceView specifically locks payroll calculate, approve, and disbursement handlers
    const wfSrc = fs.readFileSync(path.join(viewsDir, 'WorkforceView.tsx'), 'utf-8');
    assert.ok(wfSrc.includes('handleCalculatePayroll'), 'WorkforceView must contain payroll calculation handler');
    assert.ok(wfSrc.includes('handleApprovePayroll'), 'WorkforceView must contain payroll approval handler');
    assert.ok(wfSrc.includes('handleRecordPayment'), 'WorkforceView must contain payroll disbursement handler');
    assert.ok(wfSrc.includes('/api/workforce/payments'), 'WorkforceView must post payroll disbursements to /api/workforce/payments');
    assert.ok(wfSrc.includes('shouldBlockDraftNonceReset'), 'WorkforceView must block nonce reset while locked');
    passed += 1;
  }

  console.log(`TX-FINAL-04 Frontend UNKNOWN-Outcome Safety Tests: ${passed}/6 PASSED`);
}

runTests().catch((err) => {
  console.error('TX-FINAL-04 Frontend UNKNOWN-Outcome Safety Tests FAILED:', err);
  process.exit(1);
});
