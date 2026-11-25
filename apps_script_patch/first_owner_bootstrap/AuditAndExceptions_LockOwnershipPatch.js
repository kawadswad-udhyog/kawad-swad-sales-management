/**
 * Kawad Swad ERP — Isolated Pre-Merge Patch Spec for `AuditAndExceptions.js`
 * File: AuditAndExceptions_LockOwnershipPatch.js
 *
 * Status:
 *   ISOLATED PATCH SPECIFICATION ONLY — NOT MERGED INTO LIVE APPS SCRIPT.
 *
 * Verified Against Verbatim Export:
 *   File: AuditAndExceptions.js (03/43)
 *   SHA-256: 6940424567e525c209b95212e33164484866813e6575005c4245eed6cf0115e1
 *   Export lines: 281–449 (Code body starts at export line 285 = AuditAndExceptions.js line 1)
 *
 * Two Security Defects in Verbatim `ksLogAudit_` (`AuditAndExceptions.js:60-92`, export lines 344–376):
 *   1. Nested ScriptLock Release (`AuditAndExceptions.js:66`, export line 350):
 *      `ksLogAudit_` calls `ksAllocateId(KS_CONFIG.TABS.AUDIT_LOG, 'AUD_' + Utilities.getUuid())`.
 *      Without caller-owned lock propagation, `ksAllocateId` releases `ScriptLock` mid-transaction
 *      before the caller sets its completion latch or finishes multi-step persistence.
 *   2. Silent Audit Failure Swallowing (`AuditAndExceptions.js:64, 89-91`, export lines 348, 373–375):
 *      - Line 64: `if (!ss.getSheetByName(KS_CONFIG.TABS.AUDIT_LOG)) return;` silently succeeds
 *        when `AuditLog` is missing.
 *      - Lines 89–91: `catch (e) { console.error('CRITICAL AUDIT FAILURE: ' + e.message); }`
 *        swallows every allocation or SafeWriter failure without throwing, returning `undefined`.
 *
 * Design:
 *   1. Introduce `ksLogAuditStrictLocked_(action, entityType, entityId, opts)`:
 *      - Asserts `LockService.getScriptLock().hasLock() === true` (fail-closed; NEVER acquires or
 *        releases `ScriptLock`).
 *      - Allocates `audit_id` via `ksAllocateIdLocked_(KS_CONFIG.TABS.AUDIT_LOG, auditNonce)` so
 *        nested ID allocation NEVER drops the caller's `ScriptLock`.
 *      - Supports deterministic idempotent `opts.audit_nonce` (e.g. `nonce + ':AUD'`).
 *      - Persists via `ksAppendAndVerifyRow_` (`SafeWriter.js:44`) with read-back verification.
 *      - Fail-closed: THROWS on missing `AuditLog`, missing `ScriptLock`, allocation failure, or
 *        write/read-back failure (NEVER swallows exceptions).
 *      - Returns `{ audit_id, row, record }`.
 *   2. Preserve `ksLogAudit_(action, entityType, entityId, opts)` 100% backward-compatible for all
 *      existing callers, while forwarding `{ callerHoldsLock: Boolean(o.callerHoldsLock) }` to
 *      `ksAllocateId(...)` when callers opt in.
 */

/**
 * Strict, caller-locked AuditLog writer for governed security-critical transactions.
 * Caller MUST already hold `LockService.getScriptLock()`.
 * NEVER acquires or releases `ScriptLock`. NEVER swallows exceptions.
 *
 * @param {string} action
 * @param {string} entityType
 * @param {string} entityId
 * @param {Object=} opts { actor_user_id, field_changed, old_value, new_value, reason, approved_by_user_id, related_record_id, audit_nonce }
 * @return {{audit_id: string, row: number, record: Object}}
 */
function ksLogAuditStrictLocked_(action, entityType, entityId, opts) {
  if (!LockService.getScriptLock().hasLock()) {
    throw new Error('LOCK_OWNERSHIP_VIOLATION: ksLogAuditStrictLocked_ requires caller-held ScriptLock.');
  }
  if (typeof ksAllocateIdLocked_ !== 'function') {
    throw new Error('BOUND_DEPENDENCY_MISSING: ksAllocateIdLocked_ is required for caller-locked audit logging.');
  }

  const o = opts || {};
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error('MANDATORY_AUDIT_FAILED: Active spreadsheet is unavailable.');
  }
  const auditSheet = ss.getSheetByName(KS_CONFIG.TABS.AUDIT_LOG);
  if (!auditSheet) {
    throw new Error('MANDATORY_AUDIT_TAB_MISSING: AuditLog worksheet does not exist.');
  }

  const auditNonce = o.audit_nonce && String(o.audit_nonce).trim()
    ? String(o.audit_nonce).trim()
    : ('AUD_' + Utilities.getUuid());

  // Allocates audit_id WITHOUT releasing caller's ScriptLock
  const alloc = ksAllocateIdLocked_(KS_CONFIG.TABS.AUDIT_LOG, auditNonce);
  const auditId = String((alloc && alloc.allocated_id) || '').trim();
  if (!auditId || auditId.indexOf('AUD-') !== 0) {
    throw new Error('MANDATORY_AUDIT_ID_INVALID: Expected AUD-* audit_id, got "' + auditId + '".');
  }

  const auditRecord = {
    audit_id: auditId,
    event_datetime: ksNowIso_(),
    actor_user_id: o.actor_user_id || ksResolveActorId_(),
    action: action,
    entity_type: entityType,
    entity_id: entityId || '',
    field_changed: o.field_changed || '*',
    old_value: o.old_value !== undefined ? String(o.old_value) : '',
    new_value: o.new_value !== undefined ? String(o.new_value) : '',
    reason: o.reason || '',
    approved_by_user_id: o.approved_by_user_id || '',
    related_record_id: o.related_record_id || ''
  };

  const writeRes = ksAppendAndVerifyRow_(
    ss,
    KS_CONFIG.TABS.AUDIT_LOG,
    auditRecord,
    'audit_id',
    ['audit_id', 'event_datetime', 'actor_user_id', 'action', 'entity_type']
  );

  return {
    audit_id: auditId,
    row: writeRes.row,
    record: auditRecord
  };
}

/*
 * ============================================================================
 * MERGE INSTRUCTION FOR BOUND `AuditAndExceptions.js` (export lines 344–376)
 * ============================================================================
 * During authorized merge:
 *   1. Add `ksLogAuditStrictLocked_(action, entityType, entityId, opts)` above into
 *      `AuditAndExceptions.js`.
 *   2. Optionally update line 66 of `ksLogAudit_` (export line 350) from:
 *        const alloc = ksAllocateId(KS_CONFIG.TABS.AUDIT_LOG, 'AUD_' + Utilities.getUuid());
 *      to:
 *        const alloc = ksAllocateId(
 *          KS_CONFIG.TABS.AUDIT_LOG,
 *          o.audit_nonce || ('AUD_' + Utilities.getUuid()),
 *          { callerHoldsLock: Boolean(o.callerHoldsLock) }
 *        );
 *      Existing callers of `ksLogAudit_` (with 3 or 4 args and no `callerHoldsLock`) remain
 *      100% behaviorally identical.
 */
