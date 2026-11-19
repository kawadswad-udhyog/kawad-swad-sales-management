/**
 * Kawad Swad ERP — Phase 1.6 Frontend Contract & Error Mapping Regression Tests (P1.5-006).
 *
 * Verifies all 14 required Section 11 frontend contract scenarios:
 *  1. VERIFIED schema status
 *  2. BLOCKED schema status
 *  3. CONFLICT schema status
 *  4. UNKNOWN schema status (never green)
 *  5. PENDING OWNER SETUP status
 *  6. HTTP 401 unauthorized response
 *  7. HTTP 403 forbidden response
 *  8. HTTP 409 conflict / duplicate / collision response
 *  9. HTTP 422 validation error response
 * 10. HTTP 503 service unavailable (blocked owner setup + bare 503 + token revocation outage)
 * 11. Unknown / malformed API error payload
 * 12. Write blocked handling across detail.status and all 5 blocked error codes
 * 13. Loading / initial non-green empty state before authoritative backend metadata loads
 * 14. Retry state & error recovery (blocked retryable=false vs PENDING_UNKNOWN / revocation retryable=true)
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  ApiHttpError,
  BLOCKED_OWNER_SETUP_ERROR_CODES,
  classifySchemaStatusBadge,
  isBlockedOwnerSetupError,
  normalizeApiErrorPayload,
} from '../src/services/api.ts';

let passed = 0;

function runTest(name: string, fn: () => void): void {
  fn();
  passed += 1;
  console.log(`PASS: ${name}`);
}

// 1. VERIFIED
runTest('1. VERIFIED schema status renders verified badge without implying client-side write authority', () => {
  for (const s of ['VERIFIED_CORE', 'RECONCILED_OWNER_APPROVED', 'COMPLETE_VERIFIED']) {
    const badge = classifySchemaStatusBadge(s);
    assert.equal(badge.tone, 'verified');
    assert.equal(badge.writableImplied, false);
    assert.match(badge.className, /emerald/);
  }
});

// 2. BLOCKED
runTest('2. BLOCKED schema status maps strictly to red blocked badge', () => {
  const badge = classifySchemaStatusBadge('BLOCKED_PENDING_OWNER_SETUP');
  assert.equal(badge.tone, 'blocked');
  assert.match(badge.className, /red/);
  assert.doesNotMatch(badge.className, /emerald|green/);
});

// 3. CONFLICT
runTest('3. CONFLICT schema statuses map strictly to red blocked badge', () => {
  for (const s of ['CONFLICT_RECONCILIATION_REQUIRED', 'CORE_SCHEMA_CONFLICT_UNRECONCILED']) {
    const badge = classifySchemaStatusBadge(s);
    assert.equal(badge.tone, 'blocked');
    assert.match(badge.className, /red/);
    assert.doesNotMatch(badge.className, /emerald|green/);
  }
});

// 4. UNKNOWN
runTest('4. UNKNOWN / unrecognized / null schema status NEVER falls back to green', () => {
  for (const s of ['UNKNOWN_STATUS', 'CUSTOM_UNEXPECTED', '', null, undefined]) {
    const badge = classifySchemaStatusBadge(s);
    assert.equal(badge.tone, 'unknown');
    assert.doesNotMatch(badge.className, /emerald|green/);
  }
});

// 5. PENDING OWNER SETUP
runTest('5. PENDING OWNER SETUP / PENDING_OWNER_MAPPING / INCOMPLETE map to non-green pending badge', () => {
  for (const s of ['PENDING_OWNER_MAPPING', 'INCOMPLETE_PENDING_AUTHORITATIVE_WORKBOOK_EXPORT']) {
    const badge = classifySchemaStatusBadge(s);
    assert.equal(badge.tone, 'pending');
    assert.doesNotMatch(badge.className, /emerald|green/);
  }
});

// 6. HTTP 401
runTest('6. HTTP 401 authorization failure preserves auth error and is not misclassified as owner setup block', () => {
  const norm = normalizeApiErrorPayload({ detail: 'Session expired or invalid token' }, 401);
  assert.equal(norm.errorMsg, 'Session expired or invalid token');
  assert.equal(norm.workflowStatus, undefined);
  const err = new ApiHttpError(401, norm.errorMsg, 'AUTHENTICATION_REQUIRED', '/api/v2/test');
  assert.equal(isBlockedOwnerSetupError(err), false);
});

// 7. HTTP 403
runTest('7. HTTP 403 forbidden failure preserves forbidden error and is not misclassified as owner setup block', () => {
  const norm = normalizeApiErrorPayload({ detail: 'Owner role required' }, 403);
  assert.equal(norm.errorMsg, 'Owner role required');
  assert.equal(norm.workflowStatus, undefined);
  const err = new ApiHttpError(403, norm.errorMsg, 'FORBIDDEN', '/api/v2/test');
  assert.equal(isBlockedOwnerSetupError(err), false);
});

// 8. HTTP 409
runTest('8. HTTP 409 conflict / duplicate / cross-table collision preserves errorCode and retryable=false', () => {
  const norm = normalizeApiErrorPayload(
    {
      detail: {
        status: 'REJECTED',
        error_code: 'CROSS_TABLE_ID_COLLISION',
        message: 'Pre-write validation failed: RCPT-000099 collides with SalaryReceipts.',
        retryable: false,
      },
    },
    409
  );
  assert.equal(norm.errorCode, 'CROSS_TABLE_ID_COLLISION');
  assert.equal(norm.retryable, false);
  assert.match(norm.errorMsg, /RCPT-000099/);
});

// 9. HTTP 422
runTest('9. HTTP 422 validation error preserves structured errorCode and detail', () => {
  const norm = normalizeApiErrorPayload(
    {
      detail: {
        status: 'REJECTED',
        error_code: 'INVALID_PAYLOAD_ID_FORMAT',
        message: "Pre-write validation failed: 'po_id'='CUST-000001' is invalid.",
        retryable: false,
      },
    },
    422
  );
  assert.equal(norm.errorCode, 'INVALID_PAYLOAD_ID_FORMAT');
  assert.equal(norm.retryable, false);
  assert.equal(norm.workflowStatus, undefined);
});

// 10. HTTP 503
runTest('10. HTTP 503 blocked, bare 503, and token revocation outage never become success', () => {
  const blocked503 = normalizeApiErrorPayload(
    {
      detail: {
        status: 'BLOCKED_PENDING_OWNER_SETUP',
        error_code: 'CORE_SCHEMA_CONFLICT_UNRECONCILED',
        message: 'RawMaterials schema conflict unresolved',
        correlation_id: 'CORR-001',
        retryable: true,
      },
    },
    503
  );
  assert.equal(blocked503.workflowStatus, 'BLOCKED_PENDING_OWNER_SETUP');
  assert.equal(blocked503.retryable, false);

  const bare503 = normalizeApiErrorPayload(null, 503);
  assert.equal(bare503.retryable, false);
  assert.notEqual(bare503.workflowStatus, 'CONFIRMED');

  const rev503 = normalizeApiErrorPayload(
    {
      detail: {
        status: 'REJECTED',
        error_code: 'REVOCATION_STORE_UNAVAILABLE',
        message: 'Unable to verify session revocation status.',
        retryable: true,
      },
    },
    503
  );
  assert.equal(rev503.errorCode, 'REVOCATION_STORE_UNAVAILABLE');
  assert.equal(rev503.retryable, true);
  assert.equal(rev503.workflowStatus, undefined);
});

// 11. Unknown API error
runTest('11. Unknown or unstructured API error payload fails safely without throwing or returning success', () => {
  const emptyObj = normalizeApiErrorPayload({}, 500);
  assert.equal(emptyObj.errorMsg, '');
  assert.equal(emptyObj.workflowStatus, undefined);
  const undefPayload = normalizeApiErrorPayload(undefined, 502);
  assert.equal(undefPayload.errorMsg, '');
  assert.equal(isBlockedOwnerSetupError(new Error('Network down')), false);
});

// 12. Write blocked
runTest('12. Write blocked detection matches detail.status and all 5 blocked error codes', () => {
  assert.equal(BLOCKED_OWNER_SETUP_ERROR_CODES.size, 5);
  for (const code of BLOCKED_OWNER_SETUP_ERROR_CODES) {
    const norm = normalizeApiErrorPayload({ detail: { error_code: code, message: `Blocked: ${code}` } }, 503);
    assert.equal(norm.workflowStatus, 'BLOCKED_PENDING_OWNER_SETUP');
    assert.equal(norm.retryable, false);
    const err = new ApiHttpError(503, norm.errorMsg, 'BACKEND_5XX_GATEWAY', '/api/v2/write', false, {
      errorCode: norm.errorCode,
      retryable: norm.retryable,
      workflowStatus: norm.workflowStatus,
    });
    assert.equal(isBlockedOwnerSetupError(err), true);
  }
});

// 13. Loading state (ErpOperationsHubView wiring & non-green before load)
runTest('13. Loading / unloaded schema state renders unknown non-green badge and ErpOperationsHubView wires authoritative helpers', () => {
  const loadingBadge = classifySchemaStatusBadge(undefined);
  assert.equal(loadingBadge.tone, 'unknown');
  assert.doesNotMatch(loadingBadge.className, /emerald|green/);
  const hubPath = path.resolve(process.cwd(), 'src/views/ErpOperationsHubView.tsx');
  const src = fs.readFileSync(hubPath, 'utf-8');
  assert.match(src, /isBlockedOwnerSetupError/);
  assert.match(src, /classifySchemaStatusBadge/);
  assert.match(src, /unmapped_workbook_tabs_remaining/);
  assert.match(src, /write_blocked_schema_tabs_count/);
});

// 14. Retry state & recovery
runTest('14. Retryability accurately separates non-retryable blocked setup from retryable PENDING_UNKNOWN', () => {
  const blocked = normalizeApiErrorPayload(
    { detail: { status: 'BLOCKED_PENDING_OWNER_SETUP', error_code: 'PENDING_OWNER_MAPPING' } },
    503
  );
  assert.equal(blocked.retryable, false);

  const pendingUnknown = normalizeApiErrorPayload(
    { detail: { status: 'PENDING_UNKNOWN', message: 'Outcome unknown', retryable: true } },
    504
  );
  assert.equal(pendingUnknown.workflowStatus, 'PENDING_UNKNOWN');
  assert.equal(pendingUnknown.retryable, true);
  const errPending = new ApiHttpError(504, pendingUnknown.errorMsg, 'HTTP_ERROR', '/api/v2/write', false, {
    workflowStatus: pendingUnknown.workflowStatus,
    retryable: pendingUnknown.retryable,
  });
  assert.equal(isBlockedOwnerSetupError(errPending), false);
});

console.log(`\nALL ${passed}/14 PHASE 1.6 FRONTEND CONTRACT TESTS PASSED.`);
