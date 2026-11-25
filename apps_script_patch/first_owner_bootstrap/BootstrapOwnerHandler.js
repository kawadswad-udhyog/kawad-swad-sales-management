/**
 * Kawad Swad ERP — Apps Script Isolated Development Module
 * File: BootstrapOwnerHandler.js
 *
 * Purpose:
 *   Single-Write-Owner governed handler for action `BOOTSTRAP_FIRST_OWNER`.
 *   Establishes the first Owner account (`OWNER_ADMIN`, `must_change_password = "false"`)
 *   into Google Sheets (`Users` + `AuthUsers`) under `ScriptLock`, with:
 *     - Zero schema changes (preserves exact 25-col `Users`, 9-col `AuthUsers`, 5-col `IdAllocations`)
 *     - Mandatory zero-row precondition on BOTH `Users` and `AuthUsers`
 *     - Server-side PBKDF2-SHA256 hash format verification (plain-text rejected)
 *     - Constant-time bootstrap token SHA-256 digest verification + UTC expiry window
 *     - Idempotent replay & payload-conflict detection via Script Properties + `IdAllocations`
 *     - Permanent one-time completion latch (`KS_OWNER_BOOTSTRAP_COMPLETED = "true"`)
 *     - Automatic deletion of temporary bootstrap properties upon confirmation
 *     - Mandatory post-write read-back verification and sanitized AuditLog entry
 *
 * IMPORTANT — PRE-MERGE VERIFICATION REQUIRED:
 *   Because `Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip` has not yet been provided
 *   in this workspace, verify the exact bound helper signatures in the live project before
 *   merging into Apps Script:
 *     1. `ksAllocateId(...)` in `IdAllocator.js` (parameter order & `AuthUsers` prefix `AUTH` vs `AUT`)
 *     2. `ksAppendAndVerifyRow_(...)` in `SafeWriter.js`
 *     3. `ksLogAudit_(...)` in `AuditAndExceptions.js`
 *     4. `ksGetSpreadsheet_()` / active spreadsheet binding helper
 */

var KS_BOOTSTRAP_PROP_COMPLETED = 'KS_OWNER_BOOTSTRAP_COMPLETED';
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
 * Never includes passwords, hashes, or bootstrap secrets.
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
 * Convert an object record into a header-aligned row array matching the live sheet header order.
 *
 * @param {string[]} headers
 * @param {Object} record
 * @return {Array}
 */
function ksBuildRowFromHeaders_(headers, record) {
  var row = [];
  for (var i = 0; i < headers.length; i++) {
    var key = headers[i];
    var val = Object.prototype.hasOwnProperty.call(record, key) ? record[key] : '';
    row.push(val === null || val === undefined ? '' : val);
  }
  return row;
}

/**
 * Read back a row by exact key column value from a sheet (fail-closed scan).
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
 * Adapter for canonical ID allocation.
 * Delegates to the bound project's `ksAllocateId` function (verified in Mission 51B-1R-E2D).
 *
 * PRE-MERGE HOOK:
 *   Confirm the exact parameter signature of `ksAllocateId` in raw `IdAllocator.js`
 *   and confirm whether `AuthUsers` is registered under prefix `AUTH` or `AUT`.
 *
 * @param {string} tabName
 * @param {string} nonce
 * @return {string}
 */
function ksBootstrapAllocateCanonicalId_(tabName, nonce) {
  if (typeof ksAllocateId !== 'function') {
    throw new Error('BOUND_DEPENDENCY_MISSING: ksAllocateId is not defined in this Apps Script project.');
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
 * Adapter for governed append-and-verify row persistence.
 * Uses the bound project's `ksAppendAndVerifyRow_` when present; otherwise writes
 * explicitly via header-aligned row array + `SpreadsheetApp.flush()` + read-back check.
 *
 * PRE-MERGE HOOK:
 *   Confirm exact parameter order of `ksAppendAndVerifyRow_` in raw `SafeWriter.js`.
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {string[]} headers
 * @param {Object} record
 * @param {string} keyField
 */
function ksBootstrapPersistRow_(sheet, headers, record, keyField) {
  if (typeof ksAppendAndVerifyRow_ === 'function') {
    ksAppendAndVerifyRow_(sheet.getName(), record, keyField);
    return;
  }
  var rowValues = ksBuildRowFromHeaders_(headers, record);
  var targetRow = sheet.getLastRow() + 1;
  sheet.getRange(targetRow, 1, 1, rowValues.length).setValues([rowValues]);
  SpreadsheetApp.flush();
}

/**
 * Adapter for mandatory sanitized AuditLog recording.
 * Never logs password, password_hash, or bootstrap token/digest.
 *
 * PRE-MERGE HOOK:
 *   Confirm exact parameter signature of `ksLogAudit_` in raw `AuditAndExceptions.js`.
 *
 * @param {string} actor
 * @param {string} action
 * @param {string} entityType
 * @param {string} entityId
 * @param {string} reason
 */
function ksBootstrapWriteAudit_(actor, action, entityType, entityId, reason) {
  if (typeof ksLogAudit_ === 'function') {
    ksLogAudit_(actor, action, entityType, entityId, '', '', '', reason);
    return;
  }
  // Fail-closed: do not silently drop audit logging if bound helper is missing.
  throw new Error('BOUND_DEPENDENCY_MISSING: ksLogAudit_ is not defined in this Apps Script project.');
}

/**
 * Governed First-Owner Initialization Handler (`BOOTSTRAP_FIRST_OWNER`).
 *
 * Called ONLY by `ksRouteGovernedWrite_` after HMAC-SHA256 envelope authentication
 * and timestamp skew validation succeed.
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

    // 1. Permanent one-time completion latch + idempotent replay/conflict handling
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

    // 2. Verify temporary one-time bootstrap authority token hash & expiry window in Script Properties
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

    // 3. Authoritative zero-row precondition: BOTH Users and AuthUsers MUST have 0 non-blank data rows
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

    // 4. Strict server-side payload validation (never trust caller role or plain-text password)
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

    // 5. Canonical ID allocation (USR locked prefix for Users; canonical prefix for AuthUsers)
    var userId = ksBootstrapAllocateCanonicalId_('Users', nonce);
    if (userId.indexOf('USR-') !== 0) {
      return ksBootstrapResponse_(envelope, 'REJECTED', {
        error_code: 'INVALID_USER_ID_PREFIX',
        message: 'Allocated Owner user_id does not match locked USR- prefix.',
        http_status: 500,
        retryable: false
      });
    }
    var authId = ksBootstrapAllocateCanonicalId_('AuthUsers', nonce + ':AUTH');

    var nowIso = new Date().toISOString();
    var createdAt = String(payload.created_at || nowIso).trim() || nowIso;
    var updatedAt = String(payload.updated_at || createdAt).trim() || createdAt;
    var effectiveFrom = String(payload.effective_from || createdAt.slice(0, 10)).trim() || createdAt.slice(0, 10);

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

    // 6. Governed persistence into Users and AuthUsers with read-back verification
    ksBootstrapPersistRow_(usersSheet, usersHeaderCheck.headers, userRecord, 'user_id');

    try {
      ksBootstrapPersistRow_(authSheet, authHeaderCheck.headers, authRecord, 'auth_id');
    } catch (authWriteErr) {
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'PARTIAL_BOOTSTRAP_WRITE_AUTHUSERS_FAILED',
        message: 'Users row written but AuthUsers write failed; manual Owner reconciliation required.',
        http_status: 500,
        retryable: false
      });
    }

    var verifiedUsers = ksFindRowsByColumn_(usersSheet, usersHeaderCheck.headers, 'user_id', userId);
    var verifiedAuth = ksFindRowsByColumn_(authSheet, authHeaderCheck.headers, 'user_id', userId);
    if (
      verifiedUsers.length !== 1 ||
      verifiedAuth.length !== 1 ||
      String(verifiedUsers[0].role || '').trim().toUpperCase() !== 'OWNER_ADMIN' ||
      String(verifiedAuth[0].role || '').trim().toUpperCase() !== 'OWNER_ADMIN' ||
      String(verifiedAuth[0].must_change_password || '').trim().toLowerCase() !== 'false'
    ) {
      return ksBootstrapResponse_(envelope, 'RECOVERY_REQUIRED', {
        allocated_id: userId,
        error_code: 'BOOTSTRAP_READBACK_VERIFICATION_FAILED',
        message: 'Post-write read-back verification failed for Users or AuthUsers.',
        http_status: 500,
        retryable: false
      });
    }

    // 7. Set permanent completion latch and immediately erase temporary bootstrap authority properties
    props.setProperties({
      KS_OWNER_BOOTSTRAP_COMPLETED: 'true',
      KS_OWNER_BOOTSTRAP_NONCE: nonce,
      KS_OWNER_BOOTSTRAP_PAYLOAD_HASH: payloadHash,
      KS_OWNER_BOOTSTRAP_USER_ID: userId,
      KS_OWNER_BOOTSTRAP_COMPLETED_AT: nowIso
    }, false);
    props.deleteProperty(KS_BOOTSTRAP_PROP_TOKEN_HASH);
    props.deleteProperty(KS_BOOTSTRAP_PROP_EXPIRES_AT);

    // 8. Mandatory sanitized AuditLog entry (never includes password, hash, or token)
    ksBootstrapWriteAudit_(
      userId,
      'BOOTSTRAP_FIRST_OWNER',
      'Users',
      userId,
      'First Owner account initialized via governed one-time bootstrap (nonce=' + nonce + ')'
    );

    return ksBootstrapResponse_(envelope, 'CONFIRMED', {
      allocated_id: userId,
      record: userRecord,
      message: 'Initial Owner account created and verified in Google Sheets.'
    });
  } finally {
    lock.releaseLock();
  }
}
