/**
 * Kawad Swad ERP — Apps Script Isolated Development Module (Reconciled Draft — NOT MERGE-READY)
 * File: BootstrapOwnerHandler.js
 *
 * Status:
 *   ISOLATED SOURCE PACKAGE ONLY. NOT VERIFIED FOR LIVE MERGE because the raw bound
 *   Apps Script archive (`Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip`) is not yet
 *   available in this workspace.
 *
 * Purpose:
 *   Single-Write-Owner governed handler for action `BOOTSTRAP_FIRST_OWNER`.
 *   Establishes the first Owner account (`OWNER_ADMIN`, `must_change_password = "false"`)
 *   into Google Sheets (`Users` + `AuthUsers`) under `ScriptLock`, with:
 *     - Zero schema changes (preserves exact 25-col `Users`, 9-col `AuthUsers`, 5-col `IdAllocations`)
 *     - ZERO fallback bypass of `SafeWriter` (`ksAppendAndVerifyRow_`) or `AuditAndExceptions` (`ksLogAudit_`)
 *     - Mandatory zero-row precondition on BOTH `Users` and `AuthUsers`
 *     - Server-side PBKDF2-SHA256 hash format verification (plain-text rejected)
 *     - Constant-time bootstrap token SHA-256 digest verification + UTC expiry window
 *     - Idempotent replay & payload-conflict detection via Script Properties
 *     - Explicit `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED` quarantine on partial write,
 *       read-back failure, or mandatory audit failure (Mission 51B-1R-E2F O-06)
 *     - Permanent one-time completion latch (`KS_OWNER_BOOTSTRAP_COMPLETED = "true"`) set
 *       ONLY AFTER primary write, child write, read-back verification, AND mandatory audit succeed
 *     - Automatic deletion of temporary bootstrap properties on both confirmation and quarantine
 *
 * UNRESOLVED PRE-MERGE BLOCKERS (REQUIRE RAW BOUND APPS SCRIPT SOURCE):
 *   1. Confirm exact parameter order & return shape of `ksAllocateId(...)` in `IdAllocator.js`.
 *   2. Resolve `AuthUsers` prefix (`AUTH` in `backend/app/sheets.py:63` vs `AUT` in
 *      `backend/tests/v2_test_harness.py:1840`) against actual `IdAllocator.js` prefix table.
 *   3. Confirm exact parameter order of `ksAppendAndVerifyRow_(...)` in `SafeWriter.js`.
 *   4. Confirm exact parameter order of `ksLogAudit_(...)` in `AuditAndExceptions.js`.
 */

var KS_BOOTSTRAP_PROP_COMPLETED = 'KS_OWNER_BOOTSTRAP_COMPLETED';
var KS_BOOTSTRAP_PROP_RECOVERY_REQUIRED = 'KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED';
var KS_BOOTSTRAP_PROP_RECOVERY_REASON = 'KS_OWNER_BOOTSTRAP_RECOVERY_REASON';
var KS_BOOTSTRAP_PROP_TOKEN_HASH = 'KS_OWNER_BOOTSTRAP_TOKEN_HASH';
var KS_BOOTSTRAP_PROP_EXPIRES_AT = 'KS_OWNER_BOOTSTRAP_EXPIRES_AT';
var KS_BOOTSTRAP_PROP_NONCE = 'KS_OWNER_BOOTSTRAP_NONCE';
var KS_BOOTSTRAP_PROP_PAYLOAD_HASH = 'KS_OWNER_BOOTSTRAP_PAYLOAD_HASH';
var KS_BOOTSTRAP_PROP_USER_ID = 'KS_OWNER_BOOTSTRAP_USER_ID';
var KS_BOOTSTRAP_PROP_COMPLETED_AT = 'KS_OWNER_BOOTSTRAP_COMPLETED_AT';

var KS_USERS_REQUIRED_HEADERS = [
  'user_id',
  'full_name',
  'username',
  'role',
  'mobile',
  'email',
  'active',
  'created_at',
  'notes',
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
 * Read header row (row 1) of a sheet and verify every required column exists.
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {string[]} requiredHeaders
 * @return {{ok: boolean, headers: string[], missing: string[]}}
 */
function ksVerifyExactHeaders_(sheet, requiredHeaders) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < requiredHeaders.length) {
    return { ok: false, headers: [], missing: requiredHeaders.slice() };
  }
  var rawHeaders = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  var headers = [];
  var headerMap = {};
  for (var i = 0; i < rawHeaders.length; i++) {
    var h = String(rawHeaders[i] || '').trim();
    headers.push(h);
    if (h) {
      headerMap[h] = i;
    }
  }
  var missing = [];
  for (var j = 0; j < requiredHeaders.length; j++) {
    if (headerMap[requiredHeaders[j]] === undefined) {
      missing.push(requiredHeaders[j]);
    }
  }
  return { ok: missing.length === 0, headers: headers, missing: missing };
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
 * Verify all mandatory bound dependencies exist BEFORE any write or ID allocation occurs.
 * Strictly prohibits bypassing IdAllocator, SafeWriter, or AuditAndExceptions.
 *
 * @return {{ok: boolean, missing: string[]}}
 */
function ksAssertBootstrapBoundDependencies_() {
  var missing = [];
  if (typeof ksAllocateId !== 'function') {
    missing.push('ksAllocateId (IdAllocator.js)');
  }
  if (typeof ksAppendAndVerifyRow_ !== 'function') {
    missing.push('ksAppendAndVerifyRow_ (SafeWriter.js)');
  }
  if (typeof ksLogAudit_ !== 'function') {
    missing.push('ksLogAudit_ (AuditAndExceptions.js)');
  }
  return { ok: missing.length === 0, missing: missing };
}

/**
 * Adapter for canonical ID allocation (`IdAllocator.js`).
 * Fail-closed: never synthesizes IDs locally if `ksAllocateId` is unavailable.
 *
 * PRE-MERGE VERIFICATION BLOCKER:
 *   Confirm exact parameter signature & return shape of `ksAllocateId` in raw `IdAllocator.js`
 *   and confirm `AuthUsers` canonical prefix (`AUTH` vs `AUT`).
 *
 * @param {string} tabName
 * @param {string} nonce
 * @return {string}
 */
function ksBootstrapAllocateCanonicalId_(tabName, nonce) {
  if (typeof ksAllocateId !== 'function') {
    throw new Error('BOUND_DEPENDENCY_MISSING: ksAllocateId is required.');
  }
  var allocated = ksAllocateId(tabName, nonce);
  var idStr = '';
  if (typeof allocated === 'string') {
    idStr = allocated.trim();
  } else if (allocated && typeof allocated === 'object') {
    idStr = String(allocated.allocated_id || allocated.id || '').trim();
  }
  if (!idStr) {
    throw new Error('ID_ALLOCATION_EMPTY: ksAllocateId returned empty ID for ' + tabName);
  }
  return idStr;
}

/**
 * Adapter for approved SafeWriter row persistence (`SafeWriter.js`).
 * STRICT SINGLE-WRITE-OWNER RULE:
 *   NEVER falls back to direct `sheet.getRange().setValues()` or `appendRow()`.
 *   Fails closed if `ksAppendAndVerifyRow_` is absent.
 *
 * PRE-MERGE VERIFICATION BLOCKER:
 *   Confirm exact parameter order of `ksAppendAndVerifyRow_` in raw `SafeWriter.js`.
 *
 * @param {string} tabName
 * @param {Object} record
 * @param {string} keyField
 */
function ksBootstrapPersistRow_(tabName, record, keyField) {
  if (typeof ksAppendAndVerifyRow_ !== 'function') {
    throw new Error('BOUND_DEPENDENCY_MISSING: SafeWriter ksAppendAndVerifyRow_ is required (direct write fallback forbidden).');
  }
  ksAppendAndVerifyRow_(tabName, record, keyField);
}

/**
 * Adapter for mandatory sanitized AuditLog recording (`AuditAndExceptions.js`).
 * Never logs password, password_hash, or bootstrap token/digest.
 * Fails closed if `ksLogAudit_` is absent.
 *
 * PRE-MERGE VERIFICATION BLOCKER:
 *   Confirm exact parameter order of `ksLogAudit_` in raw `AuditAndExceptions.js`.
 *
 * @param {string} actor
 * @param {string} action
 * @param {string} entityType
 * @param {string} entityId
 * @param {string} reason
 */
function ksBootstrapWriteAudit_(actor, action, entityType, entityId, reason) {
  if (typeof ksLogAudit_ !== 'function') {
    throw new Error('BOUND_DEPENDENCY_MISSING: ksLogAudit_ is required (audit bypass forbidden).');
  }
  ksLogAudit_(actor, action, entityType, entityId, '', '', '', reason);
}

/**
 * Quarantine bootstrap state permanently until Owner manually reconciles partial/unverified state.
 * Immediately deletes temporary bootstrap authority properties so the one-time token cannot be reused.
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
  props.deleteProperty(KS_BOOTSTRAP_PROP_TOKEN_HASH);
  props.deleteProperty(KS_BOOTSTRAP_PROP_EXPIRES_AT);
}

/**
 * Governed First-Owner Initialization Handler (`BOOTSTRAP_FIRST_OWNER`).
 *
 * Called ONLY by `ksRouteGovernedWriteWithBootstrap_` after mandatory HMAC-SHA256
 * verification, contract_version validation, and ±300s timestamp skew check succeed.
 *
 * @param {Object} envelope Verified canonical envelope from WebAppBridge.js
 * @return {Object} Standardized Apps Script bridge response
 */
function ksBootstrapFirstOwner_(envelope) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    return ksBootstrapResponse_(envelope, 'REJECTED', {
      error_code: 'SCRIPT_LOCK_TIMEOUT',
      message: 'Could not acquire ScriptLock for first-owner initialization.',
      http_status: 503,
      retryable: true
    });
  }

  try {
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

    // 0. Fail closed immediately if a prior attempt entered RECOVERY_REQUIRED quarantine
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

    // 1. Verify all mandatory central Single-Write-Owner dependencies exist BEFORE any sheet check/write
    var depCheck = ksAssertBootstrapBoundDependencies_();
    if (!depCheck.ok) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'BOUND_WRITE_DEPENDENCIES_MISSING',
        message: 'First-owner bootstrap blocked fail-closed: missing bound helpers (' + depCheck.missing.join(', ') + ').',
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
    if (!usersSheet || !authSheet) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'REQUIRED_SHEET_MISSING',
        message: 'Users or AuthUsers tab is missing from the authoritative workbook.',
        http_status: 503,
        retryable: false
      });
    }

    var usersHeaderCheck = ksVerifyExactHeaders_(usersSheet, KS_USERS_REQUIRED_HEADERS);
    var authHeaderCheck = ksVerifyExactHeaders_(authSheet, KS_AUTH_USERS_REQUIRED_HEADERS);
    if (!usersHeaderCheck.ok || !authHeaderCheck.ok) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'SCHEMA_HEADER_MISMATCH',
        message: 'Users or AuthUsers headers do not match the canonical schema contract.',
        http_status: 503,
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
          if (existingUserRows.length === 1 && existingAuthRows.length === 1) {
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
            message: 'Bootstrap completion latch exists but Users/AuthUsers read-back is inconsistent.',
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

    // 4. Authoritative zero-row precondition: BOTH Users and AuthUsers MUST have 0 non-blank data rows
    var userRowCount = ksCountNonBlankDataRows_(usersSheet);
    var authRowCount = ksCountNonBlankDataRows_(authSheet);
    if (userRowCount > 0 || authRowCount > 0) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'OWNER_ALREADY_INITIALIZED',
        message: 'First-owner initialization refused: Users or AuthUsers already contains data rows.',
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

    // 6. Canonical ID allocation (`USR` locked prefix for Users; AuthUsers prefix pending raw IdAllocator.js verification)
    var userId = ksBootstrapAllocateCanonicalId_('Users', nonce);
    if (userId.indexOf('USR-') !== 0) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'INVALID_USER_ID_PREFIX');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'INVALID_USER_ID_PREFIX',
        message: 'Allocated Owner user_id does not match locked USR- prefix; quarantined for Owner inspection.',
        http_status: 409,
        retryable: false
      });
    }

    var authId;
    try {
      authId = ksBootstrapAllocateCanonicalId_('AuthUsers', nonce + ':AUTH');
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

    // PRE-MERGE BLOCKER: Restrict to exact single prefix once raw IdAllocator.js is inspected (AUTH vs AUT).
    if (!/^(AUTH|AUT)-[A-Za-z0-9_-]+$/.test(authId)) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'INVALID_AUTH_ID_PREFIX');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'INVALID_AUTH_ID_PREFIX',
        message: 'Allocated AuthUsers auth_id failed prefix validation; quarantined for Owner inspection.',
        http_status: 409,
        retryable: false
      });
    }

    var nowIso = new Date().toISOString();
    var createdAt = String(payload.created_at || nowIso).trim() || nowIso;
    var updatedAt = String(payload.updated_at || createdAt).trim() || createdAt;
    var effectiveFrom = createdAt.slice(0, 10);

    // Force canonical OWNER_ADMIN role, active="true", and Owner-approved must_change_password="false"
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

    // 7. Governed SafeWriter persistence into Users and AuthUsers
    try {
      ksBootstrapPersistRow_('Users', userRecord, 'user_id');
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
      ksBootstrapPersistRow_('AuthUsers', authRecord, 'auth_id');
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

    // 8. Authoritative read-back verification across BOTH Users and AuthUsers
    SpreadsheetApp.flush();
    var verifiedUsers = ksFindRowsByColumn_(usersSheet, usersHeaderCheck.headers, 'user_id', userId);
    var verifiedAuth = ksFindRowsByColumn_(authSheet, authHeaderCheck.headers, 'user_id', userId);
    if (
      verifiedUsers.length !== 1 ||
      verifiedAuth.length !== 1 ||
      String(verifiedUsers[0].role || '').trim().toUpperCase() !== 'OWNER_ADMIN' ||
      String(verifiedAuth[0].role || '').trim().toUpperCase() !== 'OWNER_ADMIN' ||
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

    // 9. Mandatory sanitized AuditLog entry BEFORE setting CONFIRMED completion latch (Mission 51B-1R-E2F O-06)
    try {
      ksBootstrapWriteAudit_(
        userId,
        'BOOTSTRAP_FIRST_OWNER',
        'Users',
        userId,
        'First Owner account initialized via governed one-time bootstrap (nonce=' + nonce + ')'
      );
    } catch (auditErr) {
      ksQuarantineBootstrapState_(props, nonce, payloadHash, userId, 'MANDATORY_AUDIT_LOG_FAILED');
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'MANDATORY_AUDIT_LOG_FAILED',
        message: 'Users and AuthUsers were written but mandatory AuditLog recording failed; quarantined for Owner reconciliation.',
        http_status: 409,
        retryable: false
      });
    }

    // 10. Set permanent completion latch and immediately erase temporary bootstrap authority properties
    props.setProperties({
      KS_OWNER_BOOTSTRAP_COMPLETED: 'true',
      KS_OWNER_BOOTSTRAP_NONCE: nonce,
      KS_OWNER_BOOTSTRAP_PAYLOAD_HASH: payloadHash,
      KS_OWNER_BOOTSTRAP_USER_ID: userId,
      KS_OWNER_BOOTSTRAP_COMPLETED_AT: nowIso
    }, false);
    props.deleteProperty(KS_BOOTSTRAP_PROP_TOKEN_HASH);
    props.deleteProperty(KS_BOOTSTRAP_PROP_EXPIRES_AT);

    return ksBootstrapResponse_(envelope, 'CONFIRMED', {
      allocated_id: userId,
      record: userRecord,
      message: 'Initial Owner account created, audited, and verified in Google Sheets.'
    });
  } finally {
    lock.releaseLock();
  }
}
