/**
 * Kawad Swad ERP — Apps Script Isolated Development Module (Lock-Hardened — NOT YET MERGED)
 * File: BootstrapOwnerHandler.js
 *
 * Status:
 *   ISOLATED SOURCE PACKAGE — RECONCILED AGAINST ALL 43 VERBATIM BOUND APPS SCRIPT FILES
 *   AND HARDENED FOR UNINTERRUPTED SCRIPTLOCK OWNERSHIP + MID-TRANSACTION CRASH RECOVERY.
 *   NOT MERGED into the live Apps Script project; no secrets provisioned; no execution performed.
 *
 * Uninterrupted ScriptLock Ownership Architecture:
 *   - `ksBootstrapFirstOwner_` acquires `LockService.getScriptLock()` ONCE at entry (`tryLock(30000)`)
 *     and releases it ONCE in its single outer `finally` block (`if (lock.hasLock()) lock.releaseLock()`).
 *   - NO nested helper called during the transaction EVER acquires or releases `ScriptLock`:
 *       * ID allocation calls `ksAllocateIdLocked_(tabName, nonce)` (`IdAllocator_LockOwnershipPatch.js`),
 *         which asserts `LockService.getScriptLock().hasLock() === true` and never calls `releaseLock()`.
 *       * Row writes call `ksAppendAndVerifyRow_(ss, tabName, recordObj, pkField, mandatoryFields)`
 *         (`SafeWriter.js:44`), which does not touch `LockService`.
 *       * Mandatory audit logging calls `ksLogAuditStrictLocked_(action, entityType, entityId, opts)`
 *         (`AuditAndExceptions_LockOwnershipPatch.js`), which asserts `hasLock() === true`, allocates
 *         `AUD-*` via `ksAllocateIdLocked_` (never releasing `ScriptLock`), persists via `SafeWriter.js`,
 *         and THROWS on any failure (never swallows exceptions like legacy `ksLogAudit_`).
 *   - Because `ScriptLock` is held without interruption from pre-check through completion latch, two
 *     simultaneous bootstrap requests are strictly serialized: the second request cannot inspect
 *     `Users`/`AuthUsers` or allocate any ID until the first request has completely committed or
 *     quarantined and released the lock.
 *
 * Crash-Recovery Architecture (Abrupt Process Termination Mid-Transaction):
 *   - Immediately BEFORE the first state mutation (`ksAllocateIdLocked_('Users', ...)`), while holding
 *     `ScriptLock`, `ksBootstrapFirstOwner_` writes a durable write-ahead marker
 *     `KS_OWNER_BOOTSTRAP_IN_PROGRESS = "true"` (with nonce, payload_hash, started_at) to Script Properties.
 *   - Because `ScriptLock` is never released mid-transaction, a subsequent request holding `ScriptLock`
 *     can ONLY observe `KS_OWNER_BOOTSTRAP_IN_PROGRESS === "true"` if a previous execution crashed
 *     abruptly (execution timeout / OOM / runtime termination where `catch`/`finally` did not run)
 *     after writing `Users` (or allocating IDs) and before writing `AuthUsers`, `AuditLog`, or
 *     setting `KS_OWNER_BOOTSTRAP_COMPLETED = "true"`.
 *   - Upon detecting `KS_OWNER_BOOTSTRAP_IN_PROGRESS === "true"` OR asymmetric sheet state
 *     (`Users` rows !== `AuthUsers` rows while `COMPLETED !== "true"`), the handler immediately
 *     promotes the state to permanent `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED = "true"`, captures any
 *     orphaned `user_id` found in `Users`/`AuthUsers`, deletes the temporary bootstrap token properties,
 *     and fails closed with `status: "RECOVERY_REQUIRED"` (HTTP 409, `retryable: false`).
 *
 * Required Co-Merged Bound Patches:
 *   1. `Config_AuthUsersPrefixPatch.js` applied to `Config.js` (`AUTH_USERS: 'AuthUsers'`, `AuthUsers: 'AUTH'`)
 *   2. `IdAllocator_LockOwnershipPatch.js` applied to `IdAllocator.js` (`ksAllocateIdLocked_`)
 *   3. `AuditAndExceptions_LockOwnershipPatch.js` applied to `AuditAndExceptions.js` (`ksLogAuditStrictLocked_`)
 *   4. `WebAppBridge_BootstrapIntegration.js` applied to `WebAppBridge.js` (`ksVerifySignedBridgeEnvelope_`
 *      + pre-lock `ksDispatchBootstrapFirstOwner_` hook before `WebAppBridge.js:71`)
 */

var KS_BOOTSTRAP_PROP_COMPLETED = 'KS_OWNER_BOOTSTRAP_COMPLETED';
var KS_BOOTSTRAP_PROP_RECOVERY_REQUIRED = 'KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED';
var KS_BOOTSTRAP_PROP_RECOVERY_REASON = 'KS_OWNER_BOOTSTRAP_RECOVERY_REASON';
var KS_BOOTSTRAP_PROP_IN_PROGRESS = 'KS_OWNER_BOOTSTRAP_IN_PROGRESS';
var KS_BOOTSTRAP_PROP_IN_PROGRESS_NONCE = 'KS_OWNER_BOOTSTRAP_IN_PROGRESS_NONCE';
var KS_BOOTSTRAP_PROP_IN_PROGRESS_PAYLOAD_HASH = 'KS_OWNER_BOOTSTRAP_IN_PROGRESS_PAYLOAD_HASH';
var KS_BOOTSTRAP_PROP_IN_PROGRESS_STARTED_AT = 'KS_OWNER_BOOTSTRAP_IN_PROGRESS_STARTED_AT';
var KS_BOOTSTRAP_PROP_TOKEN_HASH = 'KS_OWNER_BOOTSTRAP_TOKEN_HASH';
var KS_BOOTSTRAP_PROP_EXPIRES_AT = 'KS_OWNER_BOOTSTRAP_EXPIRES_AT';
var KS_BOOTSTRAP_PROP_NONCE = 'KS_OWNER_BOOTSTRAP_NONCE';
var KS_BOOTSTRAP_PROP_PAYLOAD_HASH = 'KS_OWNER_BOOTSTRAP_PAYLOAD_HASH';
var KS_BOOTSTRAP_PROP_USER_ID = 'KS_OWNER_BOOTSTRAP_USER_ID';
var KS_BOOTSTRAP_PROP_COMPLETED_AT = 'KS_OWNER_BOOTSTRAP_COMPLETED_AT';

// Exact 25-column live `Users` header set verified in both `KS_P3_MD_Header_Audit.js:25`
// (export line 5974) and `backend/app/sheets.py:128-133`. Mapped strictly by header name.
var KS_USERS_REQUIRED_HEADERS = [
  'user_id',
  'full_name',
  'role',
  'mobile',
  'email',
  'active',
  'created_at',
  'notes',
  'username',
  'employment_type',
  'designation',
  'department',
  'reporting_manager_id',
  'joining_date',
  'employment_status',
  'salary_frequency',
  'salary_structure_id',
  'address',
  'emergency_contact',
  'bank_details',
  'document_references',
  'updated_at',
  'created_by',
  'effective_from',
  'effective_to'
];

// Exact 9-column `AuthUsers` header set verified in `backend/app/sheets.py:127`
// and `KS_Phase3_Batch1A_1D_Master_Preflight_v1_0.js:41` (export line 6116).
var KS_AUTH_USERS_REQUIRED_HEADERS = [
  'auth_id',
  'user_id',
  'username',
  'password_hash',
  'role',
  'active',
  'created_at',
  'must_change_password',
  'sessions_revoked_at'
];

// Exact 5-column `IdAllocations` and 12-column `AuditLog` headers verified in
// `Config.js:121-126` (export lines 3126–3131).
var KS_ID_ALLOCATIONS_REQUIRED_HEADERS = [
  'allocation_id',
  'tab_name',
  'allocated_id',
  'nonce',
  'created_at'
];

var KS_AUDIT_LOG_REQUIRED_HEADERS = [
  'audit_id',
  'event_datetime',
  'actor_user_id',
  'action',
  'entity_type',
  'entity_id',
  'field_changed',
  'old_value',
  'new_value',
  'reason',
  'approved_by_user_id',
  'related_record_id'
];

var KS_PLACEHOLDER_OWNER_NAMES = {
  'owner': true,
  'admin': true,
  'administrator': true,
  'default': true,
  'test': true,
  'test user': true,
  'user': true,
  'owner admin': true,
  'super admin': true
};

/**
 * Constant-time string comparison for fixed-length hex digests and HMAC signatures.
 * Never short-circuits on first mismatching character.
 *
 * @param {string} a
 * @param {string} b
 * @return {boolean}
 */
function ksBootstrapSafeEqual_(a, b) {
  var sa = String(a || '');
  var sb = String(b || '');
  var lenDiff = sa.length ^ sb.length;
  var maxLen = Math.max(sa.length, sb.length);
  var diff = lenDiff;
  for (var i = 0; i < maxLen; i++) {
    var ca = i < sa.length ? sa.charCodeAt(i) : 0;
    var cb = i < sb.length ? sb.charCodeAt(i) : 0;
    diff |= (ca ^ cb);
  }
  return diff === 0 && sa.length > 0;
}

/**
 * Defense-in-depth invariant check confirming this execution still continuously owns `ScriptLock`.
 * Throws immediately if lock ownership was ever unexpectedly lost (never silently reacquires).
 *
 * @param {GoogleAppsScript.Lock.Lock} lock
 * @param {string} stage
 */
function ksAssertScriptLockHeld_(lock, stage) {
  if (!lock || !lock.hasLock()) {
    throw new Error('SCRIPTLOCK_OWNERSHIP_LOST at stage: ' + stage);
  }
}

/**
 * Build a standardized Apps Script bridge response preserving FastAPI echo fields.
 * Never includes passwords, password hashes, or bootstrap secrets.
 *
 * @param {Object} envelope
 * @param {string} status
 * @param {Object} extra
 * @return {Object}
 */
function ksBootstrapResponse_(envelope, status, extra) {
  var resp = {
    status: status,
    correlation_id: String((envelope && envelope.correlation_id) || ''),
    nonce: String((envelope && envelope.nonce) || ''),
    action: String((envelope && envelope.action) || 'BOOTSTRAP_FIRST_OWNER'),
    target_tab: String((envelope && envelope.target_tab) || 'Users')
  };
  if (extra && typeof extra === 'object') {
    var keys = Object.keys(extra);
    for (var i = 0; i < keys.length; i++) {
      resp[keys[i]] = extra[keys[i]];
    }
  }
  return resp;
}

/**
 * Validate PBKDF2-SHA256 hash format (`pbkdf2:sha256:<iterations>$<b64_salt>$<b64_dk>`).
 * Rejects plaintext, raw hashes, and weak iteration counts.
 *
 * @param {string} hashStr
 * @return {boolean}
 */
function ksValidatePbkdf2Hash_(hashStr) {
  var raw = String(hashStr || '').trim();
  var match = /^pbkdf2:sha256:(\d+)\$([A-Za-z0-9+/=]{16,})\$(([A-Za-z0-9+/=]){32,})$/.exec(raw);
  if (!match) {
    return false;
  }
  var iterations = parseInt(match[1], 10);
  return !isNaN(iterations) && iterations >= 10000 && iterations <= 2000000;
}

/**
 * Read header row (row 1) of a sheet, reject blank/duplicate headers, and verify
 * every required column exists (consistent with `SafeWriter.js:10-38`).
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {string[]} requiredHeaders
 * @return {{ok: boolean, headers: string[], missing: string[], reason: string}}
 */
function ksVerifyExactHeaders_(sheet, requiredHeaders) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < requiredHeaders.length) {
    return {
      ok: false,
      headers: [],
      missing: requiredHeaders.slice(),
      reason: 'Header row has fewer columns than required.'
    };
  }
  var rawHeaders = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var headers = [];
  var headerMap = {};
  for (var i = 0; i < rawHeaders.length; i++) {
    var h = String(rawHeaders[i] || '').trim();
    if (!h) {
      return {
        ok: false,
        headers: [],
        missing: [],
        reason: 'Blank header at column ' + (i + 1) + ' in "' + sheet.getName() + '".'
      };
    }
    if (Object.prototype.hasOwnProperty.call(headerMap, h)) {
      return {
        ok: false,
        headers: [],
        missing: [],
        reason: 'Duplicate header "' + h + '" in "' + sheet.getName() + '".'
      };
    }
    headers.push(h);
    headerMap[h] = i;
  }
  var missing = [];
  for (var j = 0; j < requiredHeaders.length; j++) {
    if (!Object.prototype.hasOwnProperty.call(headerMap, requiredHeaders[j])) {
      missing.push(requiredHeaders[j]);
    }
  }
  return {
    ok: missing.length === 0,
    headers: headers,
    missing: missing,
    reason: missing.length === 0 ? '' : ('Missing headers: ' + missing.join(', '))
  };
}

/**
 * Count non-blank data rows (row 2..lastRow) in a sheet.
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @return {number}
 */
function ksCountNonBlankDataRows_(sheet) {
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow <= 1 || lastCol <= 0) {
    return 0;
  }
  var values = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();
  var count = 0;
  for (var r = 0; r < values.length; r++) {
    var row = values[r];
    var hasValue = false;
    for (var c = 0; c < row.length; c++) {
      if (String(row[c] === null || row[c] === undefined ? '' : row[c]).trim() !== '') {
        hasValue = true;
        break;
      }
    }
    if (hasValue) {
      count++;
    }
  }
  return count;
}

/**
 * Extract the first non-blank value in a named column (used to record orphaned user_id
 * when promoting an interrupted/partial run into RECOVERY_REQUIRED quarantine).
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {string[]} headers
 * @param {string} colName
 * @return {string}
 */
function ksFindFirstNonBlankColumnValue_(sheet, headers, colName) {
  var colIdx = headers.indexOf(colName);
  if (colIdx < 0 || sheet.getLastRow() <= 1) {
    return '';
  }
  var vals = sheet.getRange(2, colIdx + 1, sheet.getLastRow() - 1, 1).getValues();
  for (var i = 0; i < vals.length; i++) {
    var v = String(vals[i][0] === null || vals[i][0] === undefined ? '' : vals[i][0]).trim();
    if (v) {
      return v;
    }
  }
  return '';
}

/**
 * Read back rows by exact key column value from a sheet (fail-closed scan).
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {string[]} headers
 * @param {string} keyCol
 * @param {string} keyVal
 * @return {Object[]}
 */
function ksFindRowsByColumn_(sheet, headers, keyCol, keyVal) {
  var colIdx = headers.indexOf(keyCol);
  if (colIdx < 0) {
    return [];
  }
  var lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    return [];
  }
  var values = sheet.getRange(2, 1, lastRow - 1, headers.length).getValues();
  var target = String(keyVal || '').trim();
  var matches = [];
  for (var r = 0; r < values.length; r++) {
    if (String(values[r][colIdx] || '').trim() === target) {
      var obj = {};
      for (var c = 0; c < headers.length; c++) {
        obj[headers[c]] = values[r][c];
      }
      matches.push(obj);
    }
  }
  return matches;
}

/**
 * Verify all mandatory bound lock-safe dependencies AND frozen `KS_CONFIG.ID_PREFIXES` entries
 * exist BEFORE any write or ID allocation occurs.
 *
 * Requires:
 *   - `ksAllocateIdLocked_` (`IdAllocator_LockOwnershipPatch.js` applied to `IdAllocator.js`)
 *   - `ksLogAuditStrictLocked_` (`AuditAndExceptions_LockOwnershipPatch.js` applied to `AuditAndExceptions.js`)
 *   - `ksAppendAndVerifyRow_` & `ksGetHeaderMap_` (`SafeWriter.js:10,44`)
 *   - `KS_CONFIG.ID_PREFIXES.Users === 'USR'`, `AuthUsers === 'AUTH'` (`Config_AuthUsersPrefixPatch.js`),
 *     and `AuditLog === 'AUD'`
 *
 * @return {{ok: boolean, errorCode: string, missing: string[]}}
 */
function ksAssertBootstrapBoundDependencies_() {
  var missing = [];
  if (typeof ksAllocateIdLocked_ !== 'function') {
    missing.push('ksAllocateIdLocked_ (apply IdAllocator_LockOwnershipPatch.js to IdAllocator.js)');
  }
  if (typeof ksLogAuditStrictLocked_ !== 'function') {
    missing.push('ksLogAuditStrictLocked_ (apply AuditAndExceptions_LockOwnershipPatch.js to AuditAndExceptions.js)');
  }
  if (typeof ksAppendAndVerifyRow_ !== 'function') {
    missing.push('ksAppendAndVerifyRow_ (SafeWriter.js)');
  }
  if (typeof ksGetHeaderMap_ !== 'function') {
    missing.push('ksGetHeaderMap_ (SafeWriter.js)');
  }
  if (typeof KS_CONFIG === 'undefined' || !KS_CONFIG || !KS_CONFIG.ID_PREFIXES || !KS_CONFIG.TABS) {
    missing.push('KS_CONFIG (Config.js)');
  }
  if (missing.length > 0) {
    return {
      ok: false,
      errorCode: 'BOUND_WRITE_DEPENDENCIES_MISSING',
      missing: missing
    };
  }

  var prefixIssues = [];
  if (KS_CONFIG.ID_PREFIXES.Users !== 'USR') {
    prefixIssues.push('KS_CONFIG.ID_PREFIXES.Users must equal "USR"');
  }
  if (KS_CONFIG.ID_PREFIXES.AuthUsers !== 'AUTH') {
    prefixIssues.push('KS_CONFIG.ID_PREFIXES.AuthUsers must equal "AUTH" (apply Config_AuthUsersPrefixPatch.js to Config.js)');
  }
  if (KS_CONFIG.ID_PREFIXES.AuditLog !== 'AUD') {
    prefixIssues.push('KS_CONFIG.ID_PREFIXES.AuditLog must equal "AUD"');
  }
  if (prefixIssues.length > 0) {
    return {
      ok: false,
      errorCode: 'CONFIG_PREFIX_CONTRACT_INCOMPLETE',
      missing: prefixIssues
    };
  }

  return { ok: true, errorCode: '', missing: [] };
}

/**
 * Caller-locked canonical ID allocation adapter (`IdAllocator_LockOwnershipPatch.js`).
 * NEVER releases or reacquires `ScriptLock`.
 *
 * @param {GoogleAppsScript.Lock.Lock} lock
 * @param {string} tabName
 * @param {string} nonce
 * @return {{status: string, allocation_id: string, allocated_id: string, tab_name: string, nonce: string}}
 */
function ksBootstrapAllocateCanonicalIdLocked_(lock, tabName, nonce) {
  ksAssertScriptLockHeld_(lock, 'BEFORE_ALLOCATE_' + tabName);
  var result = ksAllocateIdLocked_(tabName, nonce);
  ksAssertScriptLockHeld_(lock, 'AFTER_ALLOCATE_' + tabName);

  var idStr = (result && typeof result === 'object')
    ? String(result.allocated_id || '').trim()
    : '';
  if (!idStr) {
    throw new Error('ID_ALLOCATION_EMPTY: ksAllocateIdLocked_ returned empty allocated_id for ' + tabName);
  }
  return {
    status: String(result.status || ''),
    allocation_id: String(result.allocation_id || ''),
    allocated_id: idStr,
    tab_name: String(result.tab_name || tabName),
    nonce: String(result.nonce || nonce)
  };
}

/**
 * Caller-locked SafeWriter persistence adapter (`SafeWriter.js:44`).
 * NEVER falls back to direct `setValues()` or `appendRow()`.
 *
 * @param {GoogleAppsScript.Lock.Lock} lock
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} ss
 * @param {string} tabName
 * @param {Object} record
 * @param {string} keyField
 * @param {string[]} mandatoryFields
 * @return {{row: number, record: Object}}
 */
function ksBootstrapPersistRowLocked_(lock, ss, tabName, record, keyField, mandatoryFields) {
  ksAssertScriptLockHeld_(lock, 'BEFORE_WRITE_' + tabName);
  var res = ksAppendAndVerifyRow_(ss, tabName, record, keyField, mandatoryFields);
  ksAssertScriptLockHeld_(lock, 'AFTER_WRITE_' + tabName);
  return res;
}

/**
 * Caller-locked, fail-closed AuditLog persistence + independent read-back verification.
 *
 * Uses `ksLogAuditStrictLocked_` (`AuditAndExceptions_LockOwnershipPatch.js`), which:
 *   - asserts caller-held `ScriptLock` and allocates `AUD-*` via `ksAllocateIdLocked_`
 *     (NEVER releasing `ScriptLock`),
 *   - persists via `SafeWriter.js` (`ksAppendAndVerifyRow_`),
 *   - THROWS on any missing tab, allocation error, or write error (never swallows exceptions).
 *
 * Additionally performs an independent read-back scan of `AuditLog` verifying the exact
 * persisted row (`audit_id`, `action`, `entity_type`, `entity_id`, `related_record_id === nonce`)
 * before returning.
 *
 * Never logs password, password_hash, or bootstrap token/digest.
 *
 * @param {GoogleAppsScript.Lock.Lock} lock
 * @param {GoogleAppsScript.Spreadsheet.Sheet} auditSheet
 * @param {string[]} auditHeaders
 * @param {string} actorUserId
 * @param {string} entityId
 * @param {string} nonce
 * @return {string} Verified `audit_id`
 */
function ksBootstrapWriteAndVerifyAuditLocked_(lock, auditSheet, auditHeaders, actorUserId, entityId, nonce) {
  var actionName = 'BOOTSTRAP_FIRST_OWNER';
  var entityType = 'Users';

  ksAssertScriptLockHeld_(lock, 'BEFORE_AUDIT_LOG');
  var auditRes = ksLogAuditStrictLocked_(actionName, entityType, entityId, {
    actor_user_id: actorUserId,
    field_changed: 'owner_bootstrap',
    old_value: '',
    new_value: 'OWNER_ADMIN',
    reason: 'First Owner account initialized via governed one-time bootstrap (nonce=' + nonce + ')',
    approved_by_user_id: actorUserId,
    related_record_id: nonce,
    audit_nonce: nonce + ':AUD'
  });
  ksAssertScriptLockHeld_(lock, 'AFTER_AUDIT_LOG');

  var expectedAuditId = String((auditRes && auditRes.audit_id) || '').trim();
  if (!expectedAuditId || expectedAuditId.indexOf('AUD-') !== 0) {
    throw new Error('MANDATORY_AUDIT_LOG_VERIFICATION_FAILED: ksLogAuditStrictLocked_ returned invalid audit_id.');
  }

  SpreadsheetApp.flush();
  var matched = ksFindRowsByColumn_(auditSheet, auditHeaders, 'related_record_id', nonce);
  var confirmed = false;
  for (var i = 0; i < matched.length; i++) {
    var row = matched[i];
    if (
      String(row.audit_id || '').trim() === expectedAuditId &&
      String(row.action || '').trim() === actionName &&
      String(row.entity_type || '').trim() === entityType &&
      String(row.entity_id || '').trim() === String(entityId)
    ) {
      confirmed = true;
      break;
    }
  }
  if (!confirmed) {
    throw new Error('MANDATORY_AUDIT_LOG_VERIFICATION_FAILED: Independent AuditLog read-back did not find persisted BOOTSTRAP_FIRST_OWNER entry.');
  }
  return expectedAuditId;
}

/**
 * Clear the durable write-ahead IN_PROGRESS marker properties.
 *
 * @param {GoogleAppsScript.Properties.Properties} props
 */
function ksClearBootstrapInProgressProps_(props) {
  props.deleteProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS);
  props.deleteProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS_NONCE);
  props.deleteProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS_PAYLOAD_HASH);
  props.deleteProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS_STARTED_AT);
}

/**
 * Quarantine bootstrap state permanently until Owner manually reconciles partial/interrupted state.
 * Immediately clears IN_PROGRESS and deletes temporary bootstrap authority properties so the
 * one-time token can never be reused.
 *
 * @param {GoogleAppsScript.Properties.Properties} props
 * @param {string} nonce
 * @param {string} payloadHash
 * @param {string} userId
 * @param {string} reasonCode
 */
function ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, reasonCode) {
  props.setProperties({
    KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED: 'true',
    KS_OWNER_BOOTSTRAP_RECOVERY_REASON: String(reasonCode || 'BOOTSTRAP_RECOVERY_REQUIRED'),
    KS_OWNER_BOOTSTRAP_NONCE: String(nonce || ''),
    KS_OWNER_BOOTSTRAP_PAYLOAD_HASH: String(payloadHash || ''),
    KS_OWNER_BOOTSTRAP_USER_ID: String(userId || '')
  }, false);
  ksClearBootstrapInProgressProps_(props);
  props.deleteProperty(KS_BOOTSTRAP_PROP_TOKEN_HASH);
  props.deleteProperty(KS_BOOTSTRAP_PROP_EXPIRES_AT);
}

/**
 * Governed First-Owner Initialization Handler (`BOOTSTRAP_FIRST_OWNER`).
 *
 * Serializes the entire one-time initialization under a SINGLE UNINTERRUPTED `ScriptLock`
 * acquired at entry and released ONLY in the outer `finally` block.
 *
 * @param {Object} envelope Verified canonical envelope from `ksVerifySignedBridgeEnvelope_(e)`
 * @return {Object} Standardized Apps Script bridge response
 */
function ksBootstrapFirstOwner_(envelope) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    return ksBootstrapResponse_(envelope, 'REJECTED', {
      error_code: 'SCRIPT_LOCK_TIMEOUT',
      message: 'Could not acquire exclusive ScriptLock for first-owner initialization.',
      http_status: 503,
      retryable: true
    });
  }

  try {
    ksAssertScriptLockHeld_(lock, 'ENTRY');

    var props = PropertiesService.getScriptProperties();
    var nonce = String((envelope && envelope.nonce) || '').trim();
    var payloadHash = String((envelope && envelope.payload_hash) || '').trim();
    var payload = (envelope && envelope.payload && typeof envelope.payload === 'object') ? envelope.payload : {};

    if (!nonce) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'MISSING_IDEMPOTENCY_NONCE',
        message: 'Envelope nonce is mandatory for BOOTSTRAP_FIRST_OWNER.',
        http_status: 422,
        retryable: false
      });
    }

    // 0A. Fail closed immediately if already quarantined in RECOVERY_REQUIRED
    var recoveryLocked = String(props.getProperty(KS_BOOTSTRAP_PROP_RECOVERY_REQUIRED) || '').trim().toLowerCase() === 'true';
    if (recoveryLocked) {
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: String(props.getProperty(KS_BOOTSTRAP_PROP_USER_ID) || '').trim() || null,
        error_code: String(props.getProperty(KS_BOOTSTRAP_PROP_RECOVERY_REASON) || 'BOOTSTRAP_QUARANTINED_RECOVERY_REQUIRED'),
        message: 'First-owner bootstrap is quarantined in RECOVERY_REQUIRED state. Automatic retry is blocked until Owner reconciles Google Sheets.',
        http_status: 409,
        retryable: false
      });
    }

    // 1. Verify all mandatory lock-safe bound dependencies & frozen Config.js prefixes upfront
    var depCheck = ksAssertBootstrapBoundDependencies_();
    if (!depCheck.ok) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: depCheck.errorCode,
        message: 'First-owner bootstrap blocked fail-closed: ' + depCheck.missing.join('; ') + '.',
        http_status: 503,
        retryable: false
      });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    if (!ss) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'SPREADSHEET_UNAVAILABLE',
        message: 'Bound authoritative Google Spreadsheet is unavailable.',
        http_status: 503,
        retryable: true
      });
    }

    var usersSheet = ss.getSheetByName('Users');
    var authSheet = ss.getSheetByName('AuthUsers');
    var allocSheet = ss.getSheetByName(KS_CONFIG.TABS.ID_ALLOCATIONS);
    var auditSheet = ss.getSheetByName(KS_CONFIG.TABS.AUDIT_LOG);
    if (!usersSheet || !authSheet || !allocSheet || !auditSheet) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'REQUIRED_SHEET_MISSING',
        message: 'One or more required tabs (Users, AuthUsers, IdAllocations, AuditLog) are missing from the authoritative workbook.',
        http_status: 503,
        retryable: false
      });
    }

    var usersHeaderCheck = ksVerifyExactHeaders_(usersSheet, KS_USERS_REQUIRED_HEADERS);
    var authHeaderCheck = ksVerifyExactHeaders_(authSheet, KS_AUTH_USERS_REQUIRED_HEADERS);
    var allocHeaderCheck = ksVerifyExactHeaders_(allocSheet, KS_ID_ALLOCATIONS_REQUIRED_HEADERS);
    var auditHeaderCheck = ksVerifyExactHeaders_(auditSheet, KS_AUDIT_LOG_REQUIRED_HEADERS);
    if (!usersHeaderCheck.ok || !authHeaderCheck.ok || !allocHeaderCheck.ok || !auditHeaderCheck.ok) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'SCHEMA_HEADER_MISMATCH',
        message: 'Required workbook headers (Users, AuthUsers, IdAllocations, or AuditLog) failed canonical verification.',
        http_status: 503,
        retryable: false
      });
    }

    // 0B. CRASH-RECOVERY GUARD:
    // Because ScriptLock is NEVER released mid-transaction, observing IN_PROGRESS === 'true'
    // while holding ScriptLock proves a prior execution terminated abruptly after starting
    // mutation (e.g., after writing Users but before AuthUsers, AuditLog, or COMPLETED latch).
    // Immediately promote to permanent RECOVERY_REQUIRED quarantine and burn the one-time token.
    var interruptedInProgress = String(props.getProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS) || '').trim().toLowerCase() === 'true';
    if (interruptedInProgress) {
      var prevInProgressNonce = String(props.getProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS_NONCE) || '').trim();
      var prevInProgressHash = String(props.getProperty(KS_BOOTSTRAP_PROP_IN_PROGRESS_PAYLOAD_HASH) || '').trim();
      var orphanedUid = ksFindFirstNonBlankColumnValue_(usersSheet, usersHeaderCheck.headers, 'user_id') ||
        ksFindFirstNonBlankColumnValue_(authSheet, authHeaderCheck.headers, 'user_id') ||
        '';
      if (!orphanedUid && prevInProgressNonce) {
        var allocCrashRows = ksFindRowsByColumn_(allocSheet, allocHeaderCheck.headers, 'nonce', prevInProgressNonce);
        for (var ci = 0; ci < allocCrashRows.length; ci++) {
          var candAllocId = String(allocCrashRows[ci].allocated_id || '').trim();
          if (candAllocId) {
            orphanedUid = candAllocId;
            break;
          }
        }
      }
      ksQuarantineBootstrapState_(
        props,
        prevInProgressNonce || nonce,
        prevInProgressHash || payloadHash,
        orphanedUid,
        'BOOTSTRAP_CRASHED_MID_TRANSACTION'
      );
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: orphanedUid || null,
        error_code: 'BOOTSTRAP_CRASHED_MID_TRANSACTION',
        message: 'A previous first-owner bootstrap execution terminated abruptly before completing Users, AuthUsers, AuditLog, and the completion latch. State is now permanently quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }

    // 2. Permanent one-time completion latch + idempotent replay/conflict handling
    var completed = String(props.getProperty(KS_BOOTSTRAP_PROP_COMPLETED) || '').trim().toLowerCase() === 'true';
    if (completed) {
      var prevNonce = String(props.getProperty(KS_BOOTSTRAP_PROP_NONCE) || '').trim();
      var prevHash = String(props.getProperty(KS_BOOTSTRAP_PROP_PAYLOAD_HASH) || '').trim();
      var prevUid = String(props.getProperty(KS_BOOTSTRAP_PROP_USER_ID) || '').trim();

      if (prevNonce && ksBootstrapSafeEqual_(nonce, prevNonce)) {
        if (prevHash && payloadHash && ksBootstrapSafeEqual_(payloadHash, prevHash)) {
          var existingUserRows = ksFindRowsByColumn_(usersSheet, usersHeaderCheck.headers, 'user_id', prevUid);
          var existingAuthRows = ksFindRowsByColumn_(authSheet, authHeaderCheck.headers, 'user_id', prevUid);
          var existingAuditRows = ksFindRowsByColumn_(auditSheet, auditHeaderCheck.headers, 'related_record_id', prevNonce);
          var replayAuditVerified = false;
          for (var ai = 0; ai < existingAuditRows.length; ai++) {
            if (
              String(existingAuditRows[ai].action || '').trim() === 'BOOTSTRAP_FIRST_OWNER' &&
              String(existingAuditRows[ai].entity_id || '').trim() === prevUid
            ) {
              replayAuditVerified = true;
              break;
            }
          }
          if (existingUserRows.length === 1 && existingAuthRows.length === 1 && replayAuditVerified) {
            return ksBootstrapResponse_(envelope, 'CONFIRMED', {
              allocated_id: prevUid,
              record: existingUserRows[0],
              idempotent_replay: true,
              message: 'Idempotent replay confirmed for previously initialized Owner account.'
            });
          }
          return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
            allocated_id: prevUid,
            error_code: 'BOOTSTRAP_REPLAY_STATE_INCONSISTENT',
            message: 'Bootstrap completion latch exists but Users/AuthUsers/AuditLog read-back is inconsistent.',
            http_status: 409,
            retryable: false
          });
        }
        return ksBootstrapResponse_(envelope, 'REJECTED', {
          error_code: 'IDEMPOTENCY_PAYLOAD_CONFLICT',
          message: 'Bootstrap nonce was already used with a different payload.',
          http_status: 409,
          retryable: false
        });
      }

      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'OWNER_BOOTSTRAP_ALREADY_COMPLETED',
        message: 'One-time first-owner initialization has already completed and is permanently locked.',
        http_status: 409,
        retryable: false
      });
    }

    // 3. Verify temporary one-time bootstrap authority token hash & expiry window in Script Properties
    var expectedTokenHash = String(props.getProperty(KS_BOOTSTRAP_PROP_TOKEN_HASH) || '').trim().toLowerCase();
    var expiresAtRaw = String(props.getProperty(KS_BOOTSTRAP_PROP_EXPIRES_AT) || '').trim();
    if (!/^[0-9a-f]{64}$/.test(expectedTokenHash) || !expiresAtRaw) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'OWNER_BOOTSTRAP_NOT_CONFIGURED',
        message: 'Apps Script one-time bootstrap authority properties are not configured.',
        http_status: 403,
        retryable: false
      });
    }

    var expiresMs = Date.parse(expiresAtRaw);
    if (isNaN(expiresMs) || Date.now() >= expiresMs) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'OWNER_BOOTSTRAP_EXPIRED',
        message: 'One-time owner bootstrap window has expired in Apps Script.',
        http_status: 403,
        retryable: false
      });
    }

    var providedDigest = String(payload.bootstrap_token_digest || '').trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(providedDigest) || !ksBootstrapSafeEqual_(providedDigest, expectedTokenHash)) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'INVALID_BOOTSTRAP_PROOF',
        message: 'Bootstrap verification proof failed Apps Script authority check.',
        http_status: 403,
        retryable: false
      });
    }

    // 4. Authoritative zero-row precondition: BOTH Users and AuthUsers MUST have 0 non-blank data rows.
    //    If an asymmetric partial state exists (one tab populated, the other empty), quarantine immediately.
    var userRowCount = ksCountNonBlankDataRows_(usersSheet);
    var authRowCount = ksCountNonBlankDataRows_(authSheet);
    if ((userRowCount > 0 && authRowCount === 0) || (userRowCount === 0 && authRowCount > 0)) {
      var partialUid = ksFindFirstNonBlankColumnValue_(usersSheet, usersHeaderCheck.headers, 'user_id') ||
        ksFindFirstNonBlankColumnValue_(authSheet, authHeaderCheck.headers, 'user_id') ||
        '';
      ksQuarantineBootstrapState_(props, nonce, payloadHash, partialUid, 'PARTIAL_USERS_AUTHUSERS_STATE_DETECTED');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: partialUid || null,
        error_code: 'PARTIAL_USERS_AUTHUSERS_STATE_DETECTED',
        message: 'Asymmetric Users/AuthUsers state detected (one table populated, the other empty); quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }
    if (userRowCount > 0 || authRowCount > 0) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'OWNER_ALREADY_INITIALIZED',
        message: 'First-owner initialization refused: Users and AuthUsers already contain data rows.',
        http_status: 409,
        retryable: false
      });
    }

    // 5. Strict server-side payload validation (never trust caller role or plain-text password)
    var username = String(payload.username || '').trim().toLowerCase();
    var fullName = String(payload.full_name || '').trim();
    var passwordHash = String(payload.password_hash || '').trim();
    if (!/^[a-z0-9._-]{3,50}$/.test(username)) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'INVALID_USERNAME',
        message: 'Owner username does not satisfy required format.',
        http_status: 422,
        retryable: false
      });
    }
    if (fullName.length < 2 || KS_PLACEHOLDER_OWNER_NAMES[fullName.toLowerCase()]) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'INVALID_FULL_NAME',
        message: 'A real non-placeholder Owner full name is required.',
        http_status: 422,
        retryable: false
      });
    }
    if (!ksValidatePbkdf2Hash_(passwordHash)) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'INVALID_PASSWORD_HASH',
        message: 'Password must be pre-hashed with PBKDF2-SHA256 before persistence.',
        http_status: 422,
        retryable: false
      });
    }

    var nowIso = new Date().toISOString();

    var userId = '';

    // 5B. Durable Write-Ahead IN_PROGRESS marker strictly BEFORE the first ID allocation or sheet write.
    //     If GAS terminates this execution abruptly at any point from Step 6 through Step 10, the next
    //     request holding ScriptLock detects this marker at Step 0B and quarantines into RECOVERY_REQUIRED.
    //     Every unexpected exception from Step 5B onward is caught by the outer post-mutation try/catch
    //     so NO post-mutation error can ever downgrade to REJECTED/FAILED or emit a false CONFIRMED.
    try {
      ksAssertScriptLockHeld_(lock, 'BEFORE_SET_IN_PROGRESS');
      props.setProperties({
        KS_OWNER_BOOTSTRAP_IN_PROGRESS: 'true',
        KS_OWNER_BOOTSTRAP_IN_PROGRESS_NONCE: nonce,
        KS_OWNER_BOOTSTRAP_IN_PROGRESS_PAYLOAD_HASH: payloadHash,
        KS_OWNER_BOOTSTRAP_IN_PROGRESS_STARTED_AT: nowIso
      }, false);

      // 6. Canonical ID allocation via caller-locked `ksAllocateIdLocked_` (ScriptLock NEVER released!)
      var userAlloc;
      try {
        userAlloc = ksBootstrapAllocateCanonicalIdLocked_(lock, 'Users', nonce);
      } catch (userAllocErr) {
        ksQuarantineBootstrapState_(props, nonce, payloadHash, '', 'USER_ID_ALLOCATION_FAILED');
        return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
          allocated_id: null,
          error_code: 'USER_ID_ALLOCATION_FAILED',
          message: 'Users ID allocation failed after entering bootstrap transaction; quarantined for Owner inspection.',
          http_status: 409,
          retryable: false
        });
      }

      userId = userAlloc.allocated_id;
    if (!/^USR-[A-Z0-9_-]{3,}$/.test(userId)) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'INVALID_USER_ID_PREFIX');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'INVALID_USER_ID_PREFIX',
        message: 'Allocated Owner user_id does not match locked USR- prefix; quarantined for Owner inspection.',
        http_status: 409,
        retryable: false
      });
    }

    var authAlloc;
    try {
      authAlloc = ksBootstrapAllocateCanonicalIdLocked_(lock, 'AuthUsers', nonce + ':AUTH');
    } catch (authAllocErr) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'AUTH_ID_ALLOCATION_FAILED_AFTER_USER_ID');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'AUTH_ID_ALLOCATION_FAILED_AFTER_USER_ID',
        message: 'User ID was allocated but AuthUsers ID allocation failed; quarantined for Owner inspection.',
        http_status: 409,
        retryable: false
      });
    }

    var authId = authAlloc.allocated_id;
    if (!/^AUTH-[A-Z0-9_-]{3,}$/.test(authId)) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'INVALID_AUTH_ID_PREFIX');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'INVALID_AUTH_ID_PREFIX',
        message: 'Allocated AuthUsers auth_id does not match canonical AUTH- prefix; quarantined for Owner inspection.',
        http_status: 409,
        retryable: false
      });
    }

    var createdAt = String(payload.created_at || nowIso).trim() || nowIso;
    var updatedAt = String(payload.updated_at || createdAt).trim() || createdAt;
    var effectiveFrom = createdAt.slice(0, 10);

    // Force canonical OWNER_ADMIN role, active="true", and Owner-approved must_change_password="false".
    // Exact 25 keys match live `Users` Row-1 headers (`SafeWriter.js:60-62` throws on any unknown key).
    var userRecord = {
      user_id: userId,
      full_name: fullName,
      username: username,
      role: 'OWNER_ADMIN',
      mobile: String(payload.mobile || '').trim(),
      email: String(payload.email || '').trim(),
      active: 'true',
      created_at: createdAt,
      notes: String(payload.notes || 'Initial Owner account created via governed one-time bootstrap').trim(),
      employment_type: String(payload.employment_type || 'OWNER').trim(),
      designation: String(payload.designation || 'Owner / Managing Director').trim(),
      department: String(payload.department || 'Executive').trim(),
      reporting_manager_id: '',
      joining_date: effectiveFrom,
      employment_status: String(payload.employment_status || 'ACTIVE').trim(),
      salary_frequency: '',
      salary_structure_id: '',
      address: '',
      emergency_contact: '',
      bank_details: '',
      document_references: '',
      updated_at: updatedAt,
      created_by: userId,
      effective_from: effectiveFrom,
      effective_to: ''
    };

    // Exact 9 keys match `AuthUsers` Row-1 headers.
    var authRecord = {
      auth_id: authId,
      user_id: userId,
      username: username,
      password_hash: passwordHash,
      role: 'OWNER_ADMIN',
      active: 'true',
      created_at: createdAt,
      must_change_password: 'false',
      sessions_revoked_at: ''
    };

    // 7. Governed SafeWriter persistence using exact 5-arg `ksAppendAndVerifyRow_` contract
    try {
      ksBootstrapPersistRowLocked_(
        lock,
        ss,
        'Users',
        userRecord,
        'user_id',
        ['user_id', 'full_name', 'username', 'role', 'active', 'created_at']
      );
    } catch (userWriteErr) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'USERS_WRITE_FAILED_AFTER_ALLOCATION');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'USERS_WRITE_FAILED_AFTER_ALLOCATION',
        message: 'IDs were allocated but Users SafeWriter persistence failed; quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }

    try {
      ksBootstrapPersistRowLocked_(
        lock,
        ss,
        'AuthUsers',
        authRecord,
        'auth_id',
        ['auth_id', 'user_id', 'username', 'password_hash', 'role', 'active', 'created_at', 'must_change_password']
      );
    } catch (authWriteErr) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'PARTIAL_BOOTSTRAP_WRITE_AUTHUSERS_FAILED');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'PARTIAL_BOOTSTRAP_WRITE_AUTHUSERS_FAILED',
        message: 'Users row written but AuthUsers SafeWriter persistence failed; quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }

    // 8. Authoritative cross-table read-back verification across BOTH Users and AuthUsers
    SpreadsheetApp.flush();
    ksAssertScriptLockHeld_(lock, 'CROSS_TABLE_READBACK');
    var verifiedUsers = ksFindRowsByColumn_(usersSheet, usersHeaderCheck.headers, 'user_id', userId);
    var verifiedAuth = ksFindRowsByColumn_(authSheet, authHeaderCheck.headers, 'user_id', userId);
    if (
      verifiedUsers.length !== 1 ||
      verifiedAuth.length !== 1 ||
      String(verifiedUsers[0].role || '').trim().toUpperCase() !== 'OWNER_ADMIN' ||
      String(verifiedAuth[0].role || '').trim().toUpperCase() !== 'OWNER_ADMIN' ||
      String(verifiedAuth[0].auth_id || '').trim() !== authId ||
      String(verifiedAuth[0].active || '').trim().toLowerCase() !== 'true' ||
      String(verifiedAuth[0].must_change_password || '').trim().toLowerCase() !== 'false'
    ) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'BOOTSTRAP_READBACK_VERIFICATION_FAILED');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'BOOTSTRAP_READBACK_VERIFICATION_FAILED',
        message: 'Post-write read-back verification failed for Users or AuthUsers; quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }

    // 9. Mandatory fail-closed AuditLog persistence + independent read-back BEFORE completion latch (O-06)
    //    Uses `ksLogAuditStrictLocked_` (which uses `ksAllocateIdLocked_` — ScriptLock NEVER released).
    try {
      ksBootstrapWriteAndVerifyAuditLocked_(lock, auditSheet, auditHeaderCheck.headers, userId, userId, nonce);
    } catch (auditErr) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'MANDATORY_AUDIT_LOG_FAILED');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'MANDATORY_AUDIT_LOG_FAILED',
        message: 'Users and AuthUsers were written but mandatory AuditLog persistence/verification failed; quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }

    // 10. ONLY AFTER Users + AuthUsers + cross-table read-back + mandatory verified AuditLog ALL succeed:
    //     assert ScriptLock is STILL continuously held, set permanent completion latch, clear IN_PROGRESS,
    //     and immediately erase temporary bootstrap authority properties.
    ksAssertScriptLockHeld_(lock, 'BEFORE_COMPLETION_LATCH');
    props.setProperties({
      KS_OWNER_BOOTSTRAP_COMPLETED: 'true',
      KS_OWNER_BOOTSTRAP_NONCE: nonce,
      KS_OWNER_BOOTSTRAP_PAYLOAD_HASH: payloadHash,
      KS_OWNER_BOOTSTRAP_USER_ID: userId,
      KS_OWNER_BOOTSTRAP_COMPLETED_AT: nowIso
    }, false);
    ksClearBootstrapInProgressProps_(props);
    props.deleteProperty(KS_BOOTSTRAP_PROP_TOKEN_HASH);
    props.deleteProperty(KS_BOOTSTRAP_PROP_EXPIRES_AT);

      return ksBootstrapResponse_(envelope, 'CONFIRMED', {
        allocated_id: userId,
        record: userRecord,
        message: 'Initial Owner account created, audited, and verified in Google Sheets.'
      });
    } catch (unexpectedPostMutationErr) {
      // Blocker B1 guarantee: ANY unexpected exception after entering the bootstrap mutation phase
      // MUST produce RECOVERY_REQUIRED (never REJECTED/FAILED and never false CONFIRMED).
      // Partial records and audit evidence are preserved untouched; one-time token is burned.
      try {
        ksQuarantineBootstrapState_(
          props,
          nonce,
          payloadHash,
          userId || '',
          'UNEXPECTED_POST_MUTATION_EXCEPTION'
        );
      } catch (_quarantineErr) {
        // Best-effort quarantine: IN_PROGRESS remains persisted in Script Properties so the next
        // execution under ScriptLock immediately quarantines at Step 0B.
      }
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId || null,
        error_code: 'UNEXPECTED_POST_MUTATION_EXCEPTION',
        message: 'An unexpected error occurred after entering the first-owner bootstrap transaction. Partial records and audit evidence are preserved; state is quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }
  } finally {
    // Single and ONLY release point for ScriptLock across the entire bootstrap transaction.
    if (lock.hasLock()) {
      lock.releaseLock();
    }
  }
}
