/**
 * KAWAD SWAD ERP - SIGNED WEB APP BRIDGE (WebAppBridge.gs)
 * Matches backend/app/apps_script_bridge.py & backend/app/action_registry.py (Phase 1.8+)
 */

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    // 1. Mandatory HMAC-SHA256 + contract_version="2.0" + +/-300s skew verification
    //    Verifier implemented in WebAppBridge_BootstrapIntegration.js (`ksVerifySignedBridgeEnvelope_`).
    if (typeof ksVerifySignedBridgeEnvelope_ !== 'function') {
      return ksBridgeJson_({
        status: 'REJECTED',
        error_code: 'BRIDGE_AUTH_VERIFIER_MISSING',
        message: 'Mandatory ksVerifySignedBridgeEnvelope_ verifier is not loaded in Apps Script project.',
        http_status: 503,
        retryable: false
      });
    }
    const auth = ksVerifySignedBridgeEnvelope_(e);
    if (!auth.ok) {
      return ksBridgeJson_(auth.errorResponse);
    }
    const req = auth.envelope;

    const action = String(req.action || '').trim().toUpperCase();
    const targetTab = String(req.target_tab || '').trim();
    const nonce = String(req.nonce || '').trim();
    const correlationId = String(req.correlation_id || '').trim();
    const actorUserId = String(req.actor_user_id || '').trim();
    const actorRole = String(req.actor_role || '').trim().toUpperCase();
    const payload = req.payload || {};

    if (!action || !targetTab || !nonce || !correlationId) {
      return ksBridgeJson_({
        status: 'REJECTED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        error_code: 'MISSING_ENVELOPE_FIELDS',
        message: 'action, target_tab, nonce, and correlation_id are all required.'
      });
    }

    // 1B. Isolated pre-lock route for governed one-time BOOTSTRAP_FIRST_OWNER
    if (action === 'BOOTSTRAP_FIRST_OWNER') {
      return ksBridgeJson_(ksDispatchBootstrapFirstOwner_(req));
    }

    // 2. Serialize via ScriptLock & Enforce Nonce Idempotency
    lock.waitLock(20000);
    const existing = ksFindByNonce_(nonce);
    if (existing) {
      return ksBridgeJson_({
        status: 'CONFIRMED',
        idempotent_replay: true,
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        allocated_id: existing.allocated_id,
        record: existing.record || {}
      });
    }

    // 3. Execute Governed Domain Action (or Generic Canonical Table Write)
    const outcome = ksRouteGovernedWrite_(action, targetTab, payload, actorUserId, actorRole, nonce, correlationId);

    // 4. Record Nonce in IdAllocations & Log to AuditLog
    ksRecordIdAllocation_(nonce, targetTab, outcome.allocated_id || nonce);
    if (typeof ksLogAudit_ === 'function') {
      ksLogAudit_(action, targetTab, outcome.allocated_id || nonce, {
        actor_user_id: actorUserId || 'FASTAPI_GATEWAY',
        field_changed: 'governed_write',
        old_value: '',
        new_value: 'CONFIRMED | nonce=' + nonce + ' | corr=' + correlationId,
        reason: 'FastAPI Bridge: ' + action
      });
    }

    SpreadsheetApp.flush();

    // 5. Return ALL Mandatory Echo Fields Required by apps_script_bridge.py
    return ksBridgeJson_({
      status: 'CONFIRMED',
      correlation_id: correlationId,
      nonce: nonce,
      action: action,
      target_tab: targetTab,
      allocated_id: outcome.allocated_id || '',
      record: outcome.record || {}
    });

  } catch (err) {
    return ksBridgeJson_({
      status: 'REJECTED',
      error_code: 'BRIDGE_EXECUTION_ERROR',
      message: err && err.message ? err.message : String(err)
    });
  } finally {
    if (lock.hasLock()) lock.releaseLock();
  }
}

/**
 * Routes registered actions from backend/app/action_registry.py to your existing
 * Apps Script engines, falling back to safe Row-1 header-mapped sheet writes for
 * standard CRUD actions so all 15 ERP modules work immediately.
 */
function ksRouteGovernedWrite_(action, targetTab, payload, actorUserId, actorRole, nonce, correlationId) {
  // Specialized Domain Engine Dispatch (if those functions exist in your project)
  if (action === 'RECEIVE_RAW_MATERIAL' && typeof ksCreateInventoryLotAndReceipt === 'function') {
    return ksCreateInventoryLotAndReceipt(payload, nonce);
  }
  if (action === 'CREATE_PRODUCTION_ORDER' && typeof ksCreateProductionOrder === 'function') {
    return ksCreateProductionOrder(payload, nonce);
  }
  if (action === 'RECORD_MATERIAL_CONSUMPTION' && typeof ksRecordProductionConsumption === 'function') {
    return ksRecordProductionConsumption(payload, nonce);
  }
  if (action === 'RECORD_PRODUCTION_OUTPUT' && typeof ksRecordProductionOutput === 'function') {
    return ksRecordProductionOutput(payload, nonce);
  }
  if (action === 'QUALITY_CHECK_DECISION' && typeof ksRecordQualityCheckAndRelease === 'function') {
    return ksRecordQualityCheckAndRelease(payload, nonce);
  }
  if (action === 'RECORD_PACKAGING_BATCH' && typeof ksRecordPackagingOutput === 'function') {
    return ksRecordPackagingOutput(payload, nonce);
  }
  if (action === 'CREATE_SALES_ORDER' && typeof ksCreateSalesOrder === 'function') {
    return ksCreateSalesOrder(payload, nonce);
  }
  if (action === 'CREATE_SALES_INVOICE' && typeof ksCreateSalesInvoice === 'function') {
    return ksCreateSalesInvoice(payload, nonce);
  }
  if (action === 'RECORD_CUSTOMER_PAYMENT' && typeof ksRecordCustomerPayment === 'function') {
    return ksRecordCustomerPayment(payload, nonce);
  }
  if (action === 'POST_JOURNAL_VOUCHER' && typeof ksPostBalancedJournalEntry === 'function') {
    return ksPostBalancedJournalEntry(payload, nonce);
  }

  // Safe Header-Mapped Canonical Table Writer for all other action_registry.py actions
  return ksWriteCanonicalRowByHeaders_(targetTab, payload, actorUserId, nonce);
}

/**
 * Appends or updates a row in `targetTab` strictly by matching Row-1 header names
 * so FastAPI's immediate fresh=True readback verification succeeds cleanly.
 */
function ksWriteCanonicalRowByHeaders_(targetTab, payload, actorUserId, nonce) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(targetTab);
  if (!sh) {
    throw new Error('Target sheet not found: ' + targetTab);
  }

  const lastCol = sh.getLastColumn();
  if (lastCol < 1) {
    throw new Error('Target sheet has no Row-1 headers: ' + targetTab);
  }

  const headers = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim());
  const flatData = Object.assign({}, payload.record || {}, payload.updates || {}, payload);
  if (!flatData.created_at) flatData.created_at = new Date().toISOString();
  if (!flatData.created_by && actorUserId) flatData.created_by = actorUserId;
  if (!flatData.nonce) flatData.nonce = nonce;

  // Determine primary ID field (first *_id column or record_id)
  const idColIdx = headers.findIndex(h => h === 'record_id' || h.endsWith('_id'));
  const idField = idColIdx !== -1 ? headers[idColIdx] : null;
  let allocatedId = idField && flatData[idField] ? String(flatData[idField]).trim() : '';

  // Check if updating an existing row by ID
  let targetRow = -1;
  if (idField && allocatedId && sh.getLastRow() > 1) {
    const idValues = sh.getRange(2, idColIdx + 1, sh.getLastRow() - 1, 1).getValues();
    for (let i = 0; i < idValues.length; i++) {
      if (String(idValues[i][0]).trim() === allocatedId) {
        targetRow = i + 2;
        break;
      }
    }
  }

  if (targetRow !== -1) {
    const existingRow = sh.getRange(targetRow, 1, 1, lastCol).getValues()[0];
    const updatedRow = headers.map((h, idx) => (h in flatData && flatData[h] !== undefined) ? flatData[h] : existingRow[idx]);
    sh.getRange(targetRow, 1, 1, lastCol).setValues([updatedRow]);
    const savedObj = {};
    headers.forEach((h, idx) => { savedObj[h] = updatedRow[idx]; });
    return { allocated_id: allocatedId, record: savedObj };
  } else {
    const newRow = headers.map(h => (h in flatData && flatData[h] !== undefined) ? flatData[h] : '');
    sh.appendRow(newRow);
    const savedObj = {};
    headers.forEach((h, idx) => { savedObj[h] = newRow[idx]; });
    return { allocated_id: allocatedId, record: savedObj };
  }
}

function ksFindByNonce_(nonce) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName('IdAllocations');
  if (!sh || sh.getLastRow() < 2) return null;
  const data = sh.getDataRange().getValues();
  const headers = data[0].map(h => String(h).trim());
  const nIdx = headers.indexOf('nonce');
  const idIdx = headers.indexOf('allocated_id');
  const tabIdx = headers.indexOf('tab_name') !== -1 ? headers.indexOf('tab_name') : headers.indexOf('target_table');
  if (nIdx === -1) return null;
  for (let i = data.length - 1; i >= 1; i--) {
    if (String(data[i][nIdx]).trim() === nonce) {
      return {
        allocated_id: idIdx !== -1 ? String(data[i][idIdx]).trim() : '',
        tab_name: tabIdx !== -1 ? String(data[i][tabIdx]).trim() : ''
      };
    }
  }
  return null;
}

function ksRecordIdAllocation_(nonce, tabName, allocatedId) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName('IdAllocations');
  if (!sh || sh.getLastColumn() < 1) return;
  const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(h => String(h).trim());
  const row = headers.map(h => {
    if (h === 'allocation_id') return 'ALLOC-' + Date.now();
    if (h === 'tab_name' || h === 'target_table') return tabName;
    if (h === 'allocated_id') return allocatedId;
    if (h === 'nonce' || h === 'idempotency_key') return nonce;
    if (h === 'created_at') return new Date().toISOString();
    return '';
  });
  sh.appendRow(row);
}

function ksHmacSha256Hex_(message, secret) {
  const bytes = Utilities.computeHmacSha256Signature(
    String(message || ''),
    String(secret || ''),
    Utilities.Charset.UTF_8
  );
  return bytes.map(b => ('0' + (b & 0xFF).toString(16)).slice(-2)).join('');
}

function ksSafeEqual_(a, b) {
  const sa = typeof a === 'string' ? a : '';
  const sb = typeof b === 'string' ? b : '';
  const maxLen = Math.max(sa.length, sb.length);
  let diff = sa.length ^ sb.length;
  for (let i = 0; i < maxLen; i++) {
    const ca = i < sa.length ? sa.charCodeAt(i) : 0;
    const cb = i < sb.length ? sb.charCodeAt(i) : 0;
    diff |= ca ^ cb;
  }
  return diff === 0 && sa.length > 0;
}

function ksBridgeJson_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}