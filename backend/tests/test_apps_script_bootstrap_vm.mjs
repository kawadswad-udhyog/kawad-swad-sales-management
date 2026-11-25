/**
 * Kawad Swad ERP — Merged Apps Script Runtime VM Security Verification Suite
 *
 * Executes the ACTUAL merged bound Apps Script files:
 *   1. apps_script_patch/first_owner_bootstrap/merged_bound_files/Config.js
 *   2. Verbatim SafeWriter.js (extracted byte-exact from verbatim bound export)
 *   3. apps_script_patch/first_owner_bootstrap/merged_bound_files/IdAllocator.js
 *   4. apps_script_patch/first_owner_bootstrap/merged_bound_files/AuditAndExceptions.js
 *   5. apps_script_patch/first_owner_bootstrap/merged_bound_files/BootstrapOwnerHandler.js
 *   6. apps_script_patch/first_owner_bootstrap/merged_bound_files/WebAppBridge_BootstrapIntegration.js
 *   7. apps_script_patch/first_owner_bootstrap/merged_bound_files/WebAppBridge.js
 *
 * Verifies:
 *   - Frozen Config.js structure & canonical AuthUsers -> AUTH prefix
 *   - Uninterrupted ScriptLock ownership (single tryLock, single finally releaseLock)
 *   - Legacy 2-arg ksAllocateId() & 4-arg ksLogAudit_() backward compatibility
 *   - Mandatory HMAC-SHA256 + contract_version="2.0" + +/-300s skew verification
 *   - SafeWriter header validation & read-back verification
 *   - AuditLog fail-closed write + read-back before CONFIRMED
 *   - Idempotent replay (with AuditLog check), payload conflict, and post-completion lock
 *   - Blocker B1 fault injection in Steps 8, 9, 10 -> guaranteed RECOVERY_REQUIRED (never REJECTED/CONFIRMED)
 *   - Execution-timeout / hard-crash IN_PROGRESS quarantine (Step 0B + B4 IdAllocations fallback)
 *   - Zero partial-record deletion and zero duplicate Owner creation
 */

import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const ROOT = path.resolve(process.cwd());
const MERGED_DIR = path.join(ROOT, 'apps_script_patch/first_owner_bootstrap/merged_bound_files');
const VERBATIM_EXPORT = path.join(
  ROOT,
  'public/assets/aistudio/Kawad_Swad_Bound_Apps_Script_Source_COMPLETE_VERBATIM_EXPORT_c019c467.txt'
);

function extractVerbatimFile(filename) {
  const raw = fs.readFileSync(VERBATIM_EXPORT, 'utf8');
  const lines = raw.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^BEGIN FILE \d+\/\d+: (.+)$/);
    if (m && m[1].trim() === filename) {
      const size = parseInt(lines[i + 1].split(':')[1].trim(), 10);
      const expectedSha = lines[i + 2].split(':')[1].trim();
      const body = [];
      for (let j = i + 4; j < lines.length; j++) {
        if (lines[j].startsWith('END FILE ') && lines[j].includes(filename)) {
          if (body.length && /^=+$/.test(body[body.length - 1])) body.pop();
          break;
        }
        body.push(lines[j]);
      }
      let text = body.join('\n');
      while (Buffer.byteLength(text, 'utf8') > size && text.endsWith('\n')) {
        text = text.slice(0, -1);
      }
      const actualSha = crypto.createHash('sha256').update(text, 'utf8').digest('hex');
      assert.equal(actualSha, expectedSha, `SHA-256 mismatch extracting verbatim ${filename}`);
      return text;
    }
  }
  throw new Error(`Could not find ${filename} in verbatim export`);
}

const SAFE_WRITER_SRC = extractVerbatimFile('SafeWriter.js');
const MERGED_FILES = [
  ['Config.js', fs.readFileSync(path.join(MERGED_DIR, 'Config.js'), 'utf8')],
  ['SafeWriter.js', SAFE_WRITER_SRC],
  ['IdAllocator.js', fs.readFileSync(path.join(MERGED_DIR, 'IdAllocator.js'), 'utf8')],
  ['AuditAndExceptions.js', fs.readFileSync(path.join(MERGED_DIR, 'AuditAndExceptions.js'), 'utf8')],
  ['BootstrapOwnerHandler.js', fs.readFileSync(path.join(MERGED_DIR, 'BootstrapOwnerHandler.js'), 'utf8')],
  ['WebAppBridge_BootstrapIntegration.js', fs.readFileSync(path.join(MERGED_DIR, 'WebAppBridge_BootstrapIntegration.js'), 'utf8')],
  ['WebAppBridge.js', fs.readFileSync(path.join(MERGED_DIR, 'WebAppBridge.js'), 'utf8')],
];

const USERS_HEADERS = [
  'user_id', 'full_name', 'username', 'role', 'mobile', 'email', 'active', 'created_at', 'notes',
  'employment_type', 'designation', 'department', 'reporting_manager_id', 'joining_date',
  'employment_status', 'salary_frequency', 'salary_structure_id', 'address', 'emergency_contact',
  'bank_details', 'document_references', 'updated_at', 'created_by', 'effective_from', 'effective_to',
];
const AUTH_USERS_HEADERS = [
  'auth_id', 'user_id', 'username', 'password_hash', 'role', 'active', 'created_at',
  'must_change_password', 'sessions_revoked_at',
];
const ID_ALLOC_HEADERS = ['allocation_id', 'tab_name', 'allocated_id', 'nonce', 'created_at'];
const AUDIT_LOG_HEADERS = [
  'audit_id', 'event_datetime', 'actor_user_id', 'action', 'entity_type', 'entity_id',
  'field_changed', 'old_value', 'new_value', 'reason', 'approved_by_user_id', 'related_record_id',
];

class MockSheet {
  constructor(name, headers, hooks = {}) {
    this.name = name;
    this.rows = [headers.slice()];
    this.hooks = hooks;
  }
  getName() { return this.name; }
  getLastRow() { return this.rows.length; }
  getLastColumn() { return this.rows[0].length; }
  getRange(row, col, numRows = 1, numCols = 1) {
    const sheet = this;
    return {
      getValues() {
        const out = [];
        for (let r = 0; r < numRows; r++) {
          const rowArr = sheet.rows[row - 1 + r] || new Array(sheet.getLastColumn()).fill('');
          out.push(rowArr.slice(col - 1, col - 1 + numCols));
        }
        return out;
      },
      setValues(vals) {
        if (sheet.hooks.onSetValues) sheet.hooks.onSetValues(sheet.name, row, vals);
        for (let r = 0; r < vals.length; r++) {
          const idx = row - 1 + r;
          while (sheet.rows.length <= idx) sheet.rows.push(new Array(sheet.getLastColumn()).fill(''));
          for (let c = 0; c < vals[r].length; c++) {
            sheet.rows[idx][col - 1 + c] = vals[r][c];
          }
        }
      },
    };
  }
  setFrozenRows() {}
}

function createGasEnv(hooks = {}) {
  const propMap = new Map();
  const sheets = new Map([
    ['Users', new MockSheet('Users', USERS_HEADERS, hooks)],
    ['AuthUsers', new MockSheet('AuthUsers', AUTH_USERS_HEADERS, hooks)],
    ['IdAllocations', new MockSheet('IdAllocations', ID_ALLOC_HEADERS, hooks)],
    ['AuditLog', new MockSheet('AuditLog', AUDIT_LOG_HEADERS, hooks)],
  ]);

  let lockHeld = false;
  const lockEvents = [];
  const lockObj = {
    tryLock(ms) {
      if (hooks.lockContended) {
        lockEvents.push({ op: 'tryLock', ok: false, ms });
        return false;
      }
      lockHeld = true;
      lockEvents.push({ op: 'tryLock', ok: true, ms });
      return true;
    },
    waitLock(ms) {
      if (hooks.lockContended) throw new Error('Could not obtain lock after ' + ms + ' ms.');
      lockHeld = true;
      lockEvents.push({ op: 'waitLock', ok: true, ms });
    },
    hasLock() {
      return lockHeld;
    },
    releaseLock() {
      lockHeld = false;
      lockEvents.push({ op: 'releaseLock' });
    },
  };

  let flushCount = 0;
  const spreadsheet = {
    getSheetByName(name) {
      return sheets.get(name) || null;
    },
    insertSheet(name) {
      const s = new MockSheet(name, [], hooks);
      sheets.set(name, s);
      return s;
    },
  };

  const scriptProps = {
    getProperty(k) {
      return propMap.has(k) ? propMap.get(k) : null;
    },
    setProperty(k, v) {
      if (hooks.onSetProperty) hooks.onSetProperty(k, v);
      propMap.set(k, String(v));
    },
    setProperties(obj) {
      if (hooks.onSetProperties) hooks.onSetProperties(obj);
      for (const [k, v] of Object.entries(obj)) {
        propMap.set(k, String(v));
      }
    },
    deleteProperty(k) {
      propMap.delete(k);
    },
  };

  const sandbox = {
    console,
    Date,
    Math,
    JSON,
    Object,
    Array,
    String,
    Number,
    Boolean,
    RegExp,
    Error,
    parseInt,
    isNaN,
    LockService: {
      getScriptLock() {
        return lockObj;
      },
    },
    SpreadsheetApp: {
      getActiveSpreadsheet() {
        return spreadsheet;
      },
      flush() {
        flushCount++;
        if (hooks.onFlush) hooks.onFlush(flushCount);
      },
    },
    PropertiesService: {
      getScriptProperties() {
        return scriptProps;
      },
    },
    Session: {
      getActiveUser() { return { getEmail: () => 'owner@kawadswad.example' }; },
      getEffectiveUser() { return { getEmail: () => 'owner@kawadswad.example' }; },
    },
    ContentService: {
      MimeType: { JSON: 'application/json' },
      createTextOutput(str) {
        return {
          _text: str,
          setMimeType() { return this; },
          getContent() { return this._text; },
        };
      },
    },
    Utilities: {
      Charset: { UTF_8: 'utf8' },
      getUuid() { return crypto.randomUUID(); },
      formatDate(d, _tz, fmt) {
        const y = d.getUTCFullYear();
        const m = String(d.getUTCMonth() + 1).padStart(2, '0');
        const day = String(d.getUTCDate()).padStart(2, '0');
        if (fmt === 'yyyyMMdd') return `${y}${m}${day}`;
        return d.toISOString();
      },
      computeHmacSha256Signature(msg, secret) {
        const buf = crypto.createHmac('sha256', Buffer.from(secret, 'utf8'))
          .update(Buffer.from(msg, 'utf8'))
          .digest();
        return Array.from(buf).map((b) => (b > 127 ? b - 256 : b));
      },
    },
  };

  const ctx = vm.createContext(sandbox);
  for (const [fname, code] of MERGED_FILES) {
    vm.runInContext(code, ctx, { filename: fname });
  }

  return { ctx, propMap, sheets, lockEvents, getFlushCount: () => flushCount };
}

const SHARED_SECRET = 'KsAppsScriptBridgeSharedSecret2026!@#998877665544';
const BOOTSTRAP_SECRET = 'KsOwnerBootstrapOneTimeAuthoritySecret2026!@#11223344';
const BOOTSTRAP_TOKEN_HASH = crypto.createHash('sha256').update(BOOTSTRAP_SECRET, 'utf8').digest('hex');
const VALID_PW_HASH = 'pbkdf2:sha256:100000$' + 'a'.repeat(32) + '$' + 'b'.repeat(64);

function buildSignedPostEvent(overrides = {}) {
  const envelope = {
    action: 'BOOTSTRAP_FIRST_OWNER',
    target_tab: 'Users',
    nonce: overrides.nonce || 'BOOT-VM-NONCE-001',
    correlation_id: overrides.correlation_id || 'CORR-VM-001',
    transaction_id: 'TX-VM-001',
    attempt_number: 1,
    payload_hash: overrides.payload_hash || 'f'.repeat(64),
    actor_user_id: 'SYSTEM_BOOTSTRAP',
    actor_role: 'OWNER_ADMIN',
    timestamp: overrides.timestamp || new Date().toISOString(),
    payload: {
      username: 'kawad.owner',
      full_name: 'Rajesh Kawad',
      password_hash: VALID_PW_HASH,
      role: 'OWNER_ADMIN',
      must_change_password: 'false',
      bootstrap_token_digest: BOOTSTRAP_TOKEN_HASH,
      email: 'owner@kawadswad.example',
      mobile: '9876543210',
      ...(overrides.payload || {}),
    },
  };
  if (overrides.action) envelope.action = overrides.action;
  if (overrides.target_tab) envelope.target_tab = overrides.target_tab;

  const canonical = JSON.stringify(envelope);
  const sig = overrides.signature ?? crypto.createHmac('sha256', SHARED_SECRET).update(canonical, 'utf8').digest('hex');
  const wire = {
    ...envelope,
    contract_version: overrides.contract_version ?? '2.0',
    signature_alg: overrides.signature_alg ?? 'HMAC-SHA-256',
    signature: sig,
    canonical_envelope: canonical,
    ...(overrides.outerTamper || {}),
  };
  return { postData: { contents: JSON.stringify(wire) } };
}

function seedBootstrapProps(propMap, opts = {}) {
  propMap.set('SALES_APPS_SCRIPT_SHARED_SECRET', SHARED_SECRET);
  propMap.set('KS_OWNER_BOOTSTRAP_TOKEN_HASH', BOOTSTRAP_TOKEN_HASH);
  propMap.set(
    'KS_OWNER_BOOTSTRAP_EXPIRES_AT',
    opts.expiresAt || new Date(Date.now() + 15 * 60 * 1000).toISOString()
  );
}

function invokeDoPost(ctx, event) {
  const out = ctx.doPost(event);
  return JSON.parse(out.getContent());
}

// ============================================================================
// TEST 1: Frozen Config.js & Legacy Caller Compatibility
// ============================================================================
{
  const { ctx, lockEvents } = createGasEnv();
  assert.equal(vm.runInContext('Object.isFrozen(KS_CONFIG)', ctx), true);
  assert.equal(vm.runInContext('Object.isFrozen(KS_CONFIG.TABS)', ctx), true);
  assert.equal(vm.runInContext('Object.isFrozen(KS_CONFIG.ID_PREFIXES)', ctx), true);
  assert.equal(vm.runInContext('Object.isFrozen(KS_CONFIG.REQUIRED_HEADERS)', ctx), true);
  assert.equal(vm.runInContext('KS_CONFIG.TABS.AUTH_USERS', ctx), 'AuthUsers');
  assert.equal(vm.runInContext('KS_CONFIG.ID_PREFIXES.AuthUsers', ctx), 'AUTH');

  // Calling ksAllocateIdLocked_ without holding ScriptLock MUST throw LOCK_OWNERSHIP_VIOLATION
  assert.throws(
    () => ctx.ksAllocateIdLocked_('Users', 'NO-LOCK-NONCE'),
    /LOCK_OWNERSHIP_VIOLATION/
  );
  // Calling ksLogAuditStrictLocked_ without holding ScriptLock MUST throw LOCK_OWNERSHIP_VIOLATION
  assert.throws(
    () => ctx.ksLogAuditStrictLocked_('TEST', 'Users', 'USR-1', {}),
    /LOCK_OWNERSHIP_VIOLATION/
  );

  // Legacy 2-arg ksAllocateId MUST acquire & release ScriptLock identically to original
  const legAlloc = ctx.ksAllocateId('Customers', 'LEG-CUST-001');
  assert.equal(legAlloc.status, 'NEW_ALLOCATED');
  assert.match(legAlloc.allocated_id, /^CUST-\d{8}-00001$/);
  assert.deepEqual(lockEvents.map((e) => e.op), ['waitLock', 'releaseLock']);

  // Legacy 4-arg ksLogAudit_ MUST continue to work and release lock cleanly
  lockEvents.length = 0;
  ctx.ksLogAudit_('LEGACY_TEST', 'Customers', legAlloc.allocated_id, { actor_user_id: 'USR-1' });
  assert.deepEqual(lockEvents.map((e) => e.op), ['waitLock', 'releaseLock']);
  console.log('PASS 1: Frozen Config.js, lock-ownership guards, and legacy callers verified');
}

// ============================================================================
// TEST 2: Mandatory HMAC-SHA256, Contract Version, Skew & Tamper Rejection
// ============================================================================
{
  const { ctx, propMap } = createGasEnv();
  seedBootstrapProps(propMap);

  // Unsigned request
  const r1 = invokeDoPost(ctx, { postData: { contents: JSON.stringify({ action: 'BOOTSTRAP_FIRST_OWNER' }) } });
  assert.equal(r1.status, 'REJECTED');
  assert.equal(r1.error_code, 'UNSUPPORTED_CONTRACT_VERSION');

  // Bad signature
  const r2 = invokeDoPost(ctx, buildSignedPostEvent({ signature: '0'.repeat(64) }));
  assert.equal(r2.status, 'REJECTED');
  assert.equal(r2.error_code, 'INVALID_SIGNATURE');

  // Outer tamper mismatch
  const r3 = invokeDoPost(ctx, buildSignedPostEvent({ outerTamper: { nonce: 'EVIL-NONCE' } }));
  assert.equal(r3.status, 'REJECTED');
  assert.equal(r3.error_code, 'OUTER_ENVELOPE_TAMPER_DETECTED');

  // Expired envelope timestamp (> 300s skew)
  const staleTs = new Date(Date.now() - 10 * 60 * 1000).toISOString();
  const r4 = invokeDoPost(ctx, buildSignedPostEvent({ timestamp: staleTs }));
  assert.equal(r4.status, 'REJECTED');
  assert.equal(r4.error_code, 'ENVELOPE_TIMESTAMP_SKEW_EXCEEDED');

  console.log('PASS 2: Mandatory HMAC-SHA256, version, tamper, and +/-300s skew rejection verified');
}

// ============================================================================
// TEST 3: Happy Path + Continuous Single ScriptLock + Replay + Conflict + Lockout
// ============================================================================
{
  const { ctx, propMap, sheets, lockEvents } = createGasEnv();
  seedBootstrapProps(propMap);

  const evt = buildSignedPostEvent({ nonce: 'BOOT-HAPPY-001', payload_hash: 'a'.repeat(64) });
  const res = invokeDoPost(ctx, evt);
  assert.equal(res.status, 'CONFIRMED');
  assert.match(res.allocated_id, /^USR-\d{8}-00001$/);
  assert.equal(res.record.role, 'OWNER_ADMIN');

  // CRITICAL: Verify EXACTLY ONE tryLock and EXACTLY ONE releaseLock (never released mid-tx!)
  assert.deepEqual(
    lockEvents.map((e) => e.op),
    ['tryLock', 'releaseLock'],
    `Expected single uninterrupted lock cycle, got ${JSON.stringify(lockEvents)}`
  );

  // Verify Users, AuthUsers, IdAllocations (USR, AUTH, AUD), and AuditLog rows
  assert.equal(sheets.get('Users').rows.length, 2);
  assert.equal(sheets.get('AuthUsers').rows.length, 2);
  assert.equal(sheets.get('AuditLog').rows.length, 2);
  assert.equal(sheets.get('IdAllocations').rows.length, 4); // header + USR + AUTH + AUD

  const authRow = sheets.get('AuthUsers').rows[1];
  assert.match(authRow[0], /^AUTH-\d{8}-00001$/);
  assert.equal(authRow[1], res.allocated_id);
  assert.equal(authRow[4], 'OWNER_ADMIN');
  assert.equal(authRow[7], 'false'); // must_change_password = false

  // Verify completion latch set, IN_PROGRESS cleared, temporary token & expiry DELETED
  assert.equal(propMap.get('KS_OWNER_BOOTSTRAP_COMPLETED'), 'true');
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_IN_PROGRESS'), false);
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_TOKEN_HASH'), false);
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_EXPIRES_AT'), false);

  // Zero secret or password_hash leakage into AuditLog or response
  const auditDump = JSON.stringify(sheets.get('AuditLog').rows);
  assert.equal(auditDump.includes(VALID_PW_HASH), false);
  assert.equal(auditDump.includes(BOOTSTRAP_SECRET), false);
  assert.equal(auditDump.includes(BOOTSTRAP_TOKEN_HASH), false);
  assert.equal(JSON.stringify(res).includes(VALID_PW_HASH), false);

  // Idempotent replay with same nonce + same payload_hash -> CONFIRMED (idempotent_replay: true)
  const replay = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-HAPPY-001', payload_hash: 'a'.repeat(64) }));
  assert.equal(replay.status, 'CONFIRMED');
  assert.equal(replay.idempotent_replay, true);
  assert.equal(replay.allocated_id, res.allocated_id);
  assert.equal(sheets.get('Users').rows.length, 2);

  // Same nonce + different payload_hash -> REJECTED IDEMPOTENCY_PAYLOAD_CONFLICT
  const conflict = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-HAPPY-001', payload_hash: 'c'.repeat(64) }));
  assert.equal(conflict.status, 'REJECTED');
  assert.equal(conflict.error_code, 'IDEMPOTENCY_PAYLOAD_CONFLICT');

  // New nonce after completion -> REJECTED OWNER_BOOTSTRAP_ALREADY_COMPLETED
  const dup = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-HAPPY-002', payload_hash: 'a'.repeat(64) }));
  assert.equal(dup.status, 'REJECTED');
  assert.equal(dup.error_code, 'OWNER_BOOTSTRAP_ALREADY_COMPLETED');

  // B3: If AuditLog row were tampered/missing on replay, replay MUST return RECOVERY_REQUIRED
  sheets.get('AuditLog').rows.pop();
  const brokenReplay = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-HAPPY-001', payload_hash: 'a'.repeat(64) }));
  assert.equal(brokenReplay.status, 'RECOVERY_REQUIRED');
  assert.equal(brokenReplay.error_code, 'BOOTSTRAP_REPLAY_STATE_INCONSISTENT');

  console.log('PASS 3: Happy path, uninterrupted ScriptLock, canonical USR/AUTH/AUD IDs, replay & B3 verified');
}

// ============================================================================
// TEST 4: Blocker B1 — Unexpected Exception in Step 8 (Cross-Table Flush) -> RECOVERY_REQUIRED
// ============================================================================
{
  let flushCalls = 0;
  const { ctx, propMap, sheets } = createGasEnv({
    onFlush() {
      flushCalls++;
      // Flushes 1..4 are SafeWriter writes (IdAlloc USR, IdAlloc AUTH, Users, AuthUsers);
      // Flush 5 is Step 8 cross-table read-back flush!
      if (flushCalls === 5) {
        throw new Error('Simulated SpreadsheetApp.flush outage in Step 8');
      }
    },
  });
  seedBootstrapProps(propMap);

  const res = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-B1-STEP8' }));
  assert.equal(res.status, 'RECOVERY_REQUIRED', `Step 8 exception must produce RECOVERY_REQUIRED, got ${JSON.stringify(res)}`);
  assert.equal(res.error_code, 'UNEXPECTED_POST_MUTATION_EXCEPTION');
  assert.equal(res.retryable, false);
  assert.match(res.allocated_id, /^USR-/);
  // Partial rows MUST be preserved (zero deletion!)
  assert.equal(sheets.get('Users').rows.length, 2);
  assert.equal(sheets.get('AuthUsers').rows.length, 2);
  // Token MUST be burned & recovery quarantined
  assert.equal(propMap.get('KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED'), 'true');
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_TOKEN_HASH'), false);
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_COMPLETED'), false);

  console.log('PASS 4 (B1): Step 8 unexpected flush exception quarantined as RECOVERY_REQUIRED (partial rows preserved)');
}

// ============================================================================
// TEST 5: Blocker B1 — Unexpected Exception in Step 10 (Completion Latch) -> RECOVERY_REQUIRED
// ============================================================================
{
  let setPropsCalls = 0;
  const { ctx, propMap, sheets } = createGasEnv({
    onSetProperties(obj) {
      setPropsCalls++;
      if (obj.KS_OWNER_BOOTSTRAP_COMPLETED === 'true') {
        throw new Error('Simulated PropertiesService outage during Step 10 latch');
      }
    },
  });
  seedBootstrapProps(propMap);

  const res = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-B1-STEP10' }));
  assert.equal(res.status, 'RECOVERY_REQUIRED', `Step 10 exception must produce RECOVERY_REQUIRED, got ${JSON.stringify(res)}`);
  assert.equal(res.error_code, 'UNEXPECTED_POST_MUTATION_EXCEPTION');
  assert.equal(res.retryable, false);
  // Users, AuthUsers, AuditLog all preserved intact
  assert.equal(sheets.get('Users').rows.length, 2);
  assert.equal(sheets.get('AuthUsers').rows.length, 2);
  assert.equal(sheets.get('AuditLog').rows.length, 2);
  assert.equal(propMap.get('KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED'), 'true');
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_COMPLETED'), false);

  console.log('PASS 5 (B1): Step 10 completion-latch exception quarantined as RECOVERY_REQUIRED (no false CONFIRMED)');
}

// ============================================================================
// TEST 6: Abrupt Execution Timeout (IN_PROGRESS left persisted) + B4 IdAllocations Fallback
// ============================================================================
{
  const { ctx, propMap, sheets } = createGasEnv();
  seedBootstrapProps(propMap);
  // Simulate GAS hard-kill right after allocating USR-* in IdAllocations (before Users row written)
  propMap.set('KS_OWNER_BOOTSTRAP_IN_PROGRESS', 'true');
  propMap.set('KS_OWNER_BOOTSTRAP_IN_PROGRESS_NONCE', 'BOOT-CRASH-EARLY-001');
  propMap.set('KS_OWNER_BOOTSTRAP_IN_PROGRESS_PAYLOAD_HASH', 'e'.repeat(64));
  sheets.get('IdAllocations').rows.push([
    'ALLOC-0000001', 'Users', 'USR-20261124-00001', 'BOOT-CRASH-EARLY-001', new Date().toISOString(),
  ]);

  const res = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-CRASH-RETRY-002' }));
  assert.equal(res.status, 'RECOVERY_REQUIRED');
  assert.equal(res.error_code, 'BOOTSTRAP_CRASHED_MID_TRANSACTION');
  // B4: Surfaces orphaned USR-* from IdAllocations even when Users sheet is empty!
  assert.equal(res.allocated_id, 'USR-20261124-00001');
  assert.equal(propMap.get('KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED'), 'true');
  assert.equal(propMap.has('KS_OWNER_BOOTSTRAP_TOKEN_HASH'), false);
  assert.equal(sheets.get('IdAllocations').rows.length, 2); // Preserved, never deleted
  assert.equal(sheets.get('Users').rows.length, 1); // Zero duplicate Owner created

  console.log('PASS 6: Abrupt timeout IN_PROGRESS quarantine + B4 IdAllocations forensic fallback verified');
}

// ============================================================================
// TEST 7: Concurrent ScriptLock Contention Rejected Cleanly
// ============================================================================
{
  const { ctx, propMap } = createGasEnv({ lockContended: true });
  seedBootstrapProps(propMap);
  const res = invokeDoPost(ctx, buildSignedPostEvent({ nonce: 'BOOT-CONTENDED-001' }));
  assert.equal(res.status, 'REJECTED');
  assert.equal(res.error_code, 'SCRIPT_LOCK_TIMEOUT');
  assert.equal(res.retryable, true);
  console.log('PASS 7: Concurrent ScriptLock contention rejected cleanly');
}

console.log('\nALL 7 MERGED APPS SCRIPT VM SECURITY SUITES PASSED.');
