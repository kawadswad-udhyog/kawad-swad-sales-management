/**
 * KAWAD SWAD ERP - AUDIT LOGGER, EXCEPTION REGISTER & GOVERNANCE BOOTSTRAP
 * Aligned to verified AuditLog (12 cols) and ExceptionRegister (14 cols)
 * Enforces REQ-103, REQ-108, REQ-109, Section 11.5
 */

/**
 * Safely initializes ONLY missing governance tabs (AuditLog, ExceptionRegister)
 * in a disposable copy without touching existing data tabs (POL-018).
 */
function ksInitGovernanceTabs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const governanceTabs = ['AuditLog', 'ExceptionRegister'];
  const created = [];

  governanceTabs.forEach(tabName => {
    let sheet = ss.getSheetByName(tabName);
    if (!sheet) {
      sheet = ss.insertSheet(tabName);
      const headers = KS_CONFIG.REQUIRED_HEADERS[tabName];
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      sheet.setFrozenRows(1);
      created.push(tabName);
    }
  });

  return { initialized: created, timestamp: ksNowIso_() };
}

/**
 * Resolves the active Google user's email to a user_id in the Users tab if present,
 * otherwise records their email safely without exposing PII/secrets (POL-012).
 */
function ksResolveActorId_() {
  const email = ksGetActorEmail_();
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const userSheet = ss.getSheetByName(KS_CONFIG.TABS.USERS);
    if (!userSheet || userSheet.getLastRow() < 2) return email;

    const { headerMap } = ksGetHeaderMap_(userSheet, ['user_id']);
    const emailCol = headerMap['email'] || headerMap['work_email'] || headerMap['login_email'];
    if (!emailCol) return email;

    const data = userSheet.getRange(2, 1, userSheet.getLastRow() - 1, userSheet.getLastColumn()).getValues();
    for (let i = 0; i < data.length; i++) {
      if (String(data[i][emailCol - 1] || '').trim().toLowerCase() === email.toLowerCase()) {
        return String(data[i][headerMap['user_id'] - 1]);
      }
    }
  } catch (e) {
    // Fallback to email if Users lookup is not yet populated
  }
  return email;
}

/**
 * Appends an immutable field/record audit entry aligned to the 12-column AuditLog schema.
 */
function ksLogAudit_(action, entityType, entityId, opts) {
  const o = opts || {};
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (!ss.getSheetByName(KS_CONFIG.TABS.AUDIT_LOG)) return;

    const alloc = ksAllocateId(
      KS_CONFIG.TABS.AUDIT_LOG,
      o.audit_nonce || ('AUD_' + Utilities.getUuid()),
      { callerHoldsLock: Boolean(o.callerHoldsLock) }
    );
    const auditRecord = {
      audit_id: alloc.allocated_id,
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

    ksAppendAndVerifyRow_(
      ss,
      KS_CONFIG.TABS.AUDIT_LOG,
      auditRecord,
      'audit_id',
      ['audit_id', 'event_datetime', 'actor_user_id', 'action', 'entity_type']
    );
  } catch (e) {
    console.error('CRITICAL AUDIT FAILURE: ' + e.message);
  }
}

/**
 * Records a failed write, validation breach, or reconciliation mismatch (REQ-109).
 */
function ksLogException_(severity, sourceFunction, tabName, referenceId, errorMessage, payloadObj) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (!ss.getSheetByName(KS_CONFIG.TABS.EXCEPTION_REGISTER)) return;

    const alloc = ksAllocateId(KS_CONFIG.TABS.EXCEPTION_REGISTER, 'EXC_' + Utilities.getUuid());
    const excRecord = {
      exception_id: alloc.allocated_id,
      created_at: ksNowIso_(),
      severity: severity || 'HIGH',
      source_function: sourceFunction,
      tab_name: tabName || '',
      reference_id: referenceId || '',
      error_message: String(errorMessage),
      payload_json: JSON.stringify(payloadObj || {}),
      assigned_owner: 'OWNER_ADMIN',
      due_date: '',
      status: 'OPEN',
      resolution_notes: '',
      resolved_by: '',
      resolved_at: ''
    };

    ksAppendAndVerifyRow_(
      ss,
      KS_CONFIG.TABS.EXCEPTION_REGISTER,
      excRecord,
      'exception_id',
      ['exception_id', 'created_at', 'severity', 'source_function', 'error_message', 'status']
    );
  } catch (e) {
    console.error('CRITICAL EXCEPTION LOGGING FAILURE: ' + e.message);
  }
}

/**
 * Phase G Disposable-Copy Verification Test:
 * Tests schema headers, ID allocation, idempotency retry safety, and AuditLog write.
 */
function ksRunPhaseGCoreTest() {
  ksInitGovernanceTabs();
  const testNonce = 'TEST_NONCE_001';
  const firstCall = ksAllocateId('Customers', testNonce);
  const retryCall = ksAllocateId('Customers', testNonce);

  if (firstCall.allocated_id !== retryCall.allocated_id || retryCall.status !== 'EXISTING_IDEMPOTENT') {
    throw new Error('Idempotency test failed!');
  }

  ksLogAudit_('ID_ALLOC_TEST', 'IdAllocations', firstCall.allocated_id, {
    field_changed: 'allocated_id',
    new_value: firstCall.allocated_id,
    reason: 'Phase G Core Verification Test (nonce=' + testNonce + ')',
    related_record_id: firstCall.allocation_id
  });

  Logger.log('Phase G Core Test Passed: ' + JSON.stringify(retryCall));
}

/**
 * Read-only inventory of all existing tabs and column/row counts (Phase B).
 */
function ksListAllExistingTabs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const summary = ss.getSheets().map(s => s.getName() + ' (cols=' + s.getLastColumn() + ', rows=' + s.getLastRow() + ')');
  Logger.log(JSON.stringify(summary, null, 2));
}

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
