/**
 * KAWAD SWAD ERP - SIGNED WEB APP BRIDGE (WebAppBridge.gs)
 * Matches backend/app/apps_script_bridge.py & backend/app/action_registry.py (Phase 1.8+)
 */

const KS_BRIDGE_PROTECTED_GOVERNANCE_TABS = Object.freeze({
  AuditLog: true,
  IdAllocations: true,
  ExceptionRegister: true
});

const KS_BRIDGE_FORBIDDEN_SCRATCH_RE = /^(?:KS_P1_|KS_P2_|KS_P3_|DBV5_|DB_)/i;

const KS_BRIDGE_AUTH_USERS_ALLOWED_ACTIONS = Object.freeze({
  REVOKE_USER_SESSIONS: true,
  CHANGE_PASSWORD: true,
  RESET_PASSWORD: true
});

const KS_BRIDGE_ALLOWED_TARGET_TABS = Object.freeze({
  // Canonical target_tab allowlist matching backend/app/action_registry.py (55 tabs)
  AccountingPeriods: true,
  ApprovalRequests: true,
  AssetsMaintenance: true,
  AuthUsers: true,
  ComplaintsRecalls: true,
  ComplianceRecords: true,
  CustomRoles: true,
  CustomerReturns: true,
  Customers: true,
  DailyClosing: true,
  EmployeeAdvances: true,
  EmployeeAttendance: true,
  Expenses: true,
  FreelancerMilestones: true,
  FreelancerProjects: true,
  GoodsReceipts: true,
  JournalHeaders: true,
  LabourAttendance: true,
  LabourMaster: true,
  LabourWorkEntries: true,
  MarketplaceSettlements: true,
  MillingBatches: true,
  PackagingBatches: true,
  Payments: true,
  PayrollItems: true,
  PayrollRuns: true,
  ProductLots: true,
  ProductionBatches: true,
  ProductionDispatches: true,
  ProductionStockLedger: true,
  Products: true,
  PurchaseOrders: true,
  QualityChecks: true,
  RawMaterialLedger: true,
  RawMaterials: true,
  Recipes: true,
  RevokedTokens: true,
  SalaryIncentives: true,
  SalaryStructures: true,
  Sales: true,
  SalesOrders: true,
  SalesmanStockLedger: true,
  Settings: true,
  ShopVisits: true,
  StockDiscrepancies: true,
  SupplierBills: true,
  SupplierPayments: true,
  SupplierReturns: true,
  Suppliers: true,
  Users: true,
  VanLoadingPasses: true,
  WorkAssignments: true,
  WorkerAttendance: true,
  Workers: true,
  WorkforcePayments: true,
  // Canonical Blueprint v2 Apps Script engine target tabs (Config.js ID_PREFIXES, non-governance)
  CustomerPaymentAllocations: true,
  CustomerPayments: true,
  DamagedStock: true,
  DeliveryProof: true,
  DeliveryTracking: true,
  DocumentRegister: true,
  Employees: true,
  ExpiredStock: true,
  FactoryLocations: true,
  FinancialPeriods: true,
  FinishedGoodsQualityChecks: true,
  GeneralLedger: true,
  HoldReleaseRecords: true,
  InProcessQualityChecks: true,
  IncomingQualityChecks: true,
  InventoryBalances: true,
  InventoryLots: true,
  InventoryMovements: true,
  JournalEntries: true,
  JournalEntryLines: true,
  LeaveRecords: true,
  MaterialConsumption: true,
  MaterialIssues: true,
  OrderCancellations: true,
  OrderStatusHistory: true,
  OvertimeRecords: true,
  PackagingLosses: true,
  PackagingMaterials: true,
  PackagingOutputs: true,
  PackagingPlans: true,
  PaymentAllocations: true,
  ProcessLosses: true,
  ProductPrices: true,
  ProductionOrders: true,
  ProductionOutputs: true,
  ProductionPlans: true,
  ProductionWorkerEntries: true,
  PurchaseRequisitions: true,
  QuarantineStock: true,
  RecipeIngredients: true,
  RecipeVersions: true,
  SalaryPayments: true,
  SalesInvoiceItems: true,
  SalesInvoices: true,
  SalesOrderItems: true,
  SalesReturnItems: true,
  SalesReturns: true,
  ShiftSchedules: true,
  ShipmentItems: true,
  Shipments: true,
  StockAdjustments: true,
  StockCountLines: true,
  StockCounts: true,
  StockReservations: true,
  StockTransferItems: true,
  StockTransfers: true,
  SupplierQuotations: true,
  SystemConfig: true,
  Warehouses: true,
  BankTransactions: true,
  CreditNotes: true
});

/**
 * Fail-closed target-table allowlist and governance/scratch/AuthUsers guard (Stage 1 W3).
 */
function ksValidateBridgeTargetTab_(action, targetTab) {
  if (Object.prototype.hasOwnProperty.call(KS_BRIDGE_PROTECTED_GOVERNANCE_TABS, targetTab)) {
    return {
      ok: false,
      error_code: 'GOVERNANCE_TAB_WRITE_FORBIDDEN',
      http_status: 403,
      message: 'Direct bridge mutation of immutable governance tab "' + targetTab + '" is forbidden.'
    };
  }
  if (KS_BRIDGE_FORBIDDEN_SCRATCH_RE.test(targetTab)) {
    return {
      ok: false,
      error_code: 'SCRATCH_TAB_FORBIDDEN',
      http_status: 403,
      message: 'Legacy scratch tab "' + targetTab + '" is forbidden (POL-003).'
    };
  }
  if (
    targetTab === 'AuthUsers' &&
    !Object.prototype.hasOwnProperty.call(KS_BRIDGE_AUTH_USERS_ALLOWED_ACTIONS, action)
  ) {
    return {
      ok: false,
      error_code: 'AUTH_USERS_ACTION_FORBIDDEN',
      http_status: 403,
      message: 'Action "' + action + '" is not authorized to mutate AuthUsers.'
    };
  }
  if (!Object.prototype.hasOwnProperty.call(KS_BRIDGE_ALLOWED_TARGET_TABS, targetTab)) {
    return {
      ok: false,
      error_code: 'UNAPPROVED_TARGET_TAB',
      http_status: 403,
      message: 'Target tab "' + targetTab + '" is not in the approved canonical bridge allowlist.'
    };
  }
  return { ok: true };
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  let action = '';
  let targetTab = '';
  let nonce = '';
  let correlationId = '';
  let businessWriteAttempted = false;
  let outcome = null;

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

    action = String(req.action || '').trim().toUpperCase();
    targetTab = String(req.target_tab || '').trim();
    nonce = String(req.nonce || '').trim();
    correlationId = String(req.correlation_id || '').trim();
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
        message: 'action, target_tab, nonce, and correlation_id are all required.',
        http_status: 400,
        retryable: false
      });
    }

    if (!actorUserId || !actorRole) {
      return ksBridgeJson_({
        status: 'REJECTED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        error_code: 'MISSING_ACTOR_IDENTITY',
        message: 'Authenticated actor_user_id and actor_role are mandatory for all governed bridge writes.',
        http_status: 401,
        retryable: false
      });
    }

    // 1B. Isolated pre-lock route for governed one-time BOOTSTRAP_FIRST_OWNER
    if (action === 'BOOTSTRAP_FIRST_OWNER') {
      return ksBridgeJson_(ksDispatchBootstrapFirstOwner_(req));
    }

    // 1C. Fail-closed target-table allowlist & governance/scratch/AuthUsers guard
    const tabCheck = ksValidateBridgeTargetTab_(action, targetTab);
    if (!tabCheck.ok) {
      return ksBridgeJson_({
        status: 'REJECTED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        error_code: tabCheck.error_code,
        message: tabCheck.message,
        http_status: tabCheck.http_status,
        retryable: false
      });
    }

    // 1D. Fail-closed check: mandatory audit logger must be loaded before any write
    if (typeof ksLogAuditStrictLocked_ !== 'function' && typeof ksLogAudit_ !== 'function') {
      return ksBridgeJson_({
        status: 'REJECTED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        error_code: 'MANDATORY_AUDIT_LOGGER_MISSING',
        message: 'Mandatory audit logger is not loaded in Apps Script project.',
        http_status: 503,
        retryable: false
      });
    }

    // 2. Serialize via ScriptLock & Enforce Nonce + Target-Tab Idempotency
    lock.waitLock(20000);
    const existing = ksFindByNonce_(nonce);
    if (existing) {
      if (existing.tab_name && existing.tab_name !== targetTab) {
        return ksBridgeJson_({
          status: 'REJECTED',
          correlation_id: correlationId,
          nonce: nonce,
          action: action,
          target_tab: targetTab,
          error_code: 'NONCE_TARGET_TAB_CONFLICT',
          message: 'Nonce "' + nonce + '" is already bound to tab "' + existing.tab_name + '", cannot replay on "' + targetTab + '".',
          http_status: 409,
          retryable: false
        });
      }
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

    // 3. Execute Governed Domain Action (or Header-Mapped Canonical Table Write with Read-Back)
    businessWriteAttempted = true;
    outcome = ksRouteGovernedWrite_(action, targetTab, payload, actorUserId, actorRole, nonce, correlationId);

    // 4. Record Monotonic Nonce in IdAllocations & Write Strict Lock-Preserving AuditLog
    ksRecordIdAllocation_(nonce, targetTab, (outcome && outcome.allocated_id) || nonce);

    const auditOpts = {
      actor_user_id: actorUserId,
      field_changed: 'governed_write',
      old_value: '',
      new_value: 'CONFIRMED | nonce=' + nonce + ' | corr=' + correlationId,
      reason: 'FastAPI Bridge: ' + action,
      audit_nonce: 'AUD_BRIDGE_' + nonce,
      callerHoldsLock: true
    };
    if (typeof ksLogAuditStrictLocked_ === 'function') {
      ksLogAuditStrictLocked_(action, targetTab, (outcome && outcome.allocated_id) || nonce, auditOpts);
    } else {
      ksLogAudit_(action, targetTab, (outcome && outcome.allocated_id) || nonce, auditOpts);
    }

    SpreadsheetApp.flush();

    // 5. Return ALL Mandatory Echo Fields Required by apps_script_bridge.py
    return ksBridgeJson_({
      status: 'CONFIRMED',
      correlation_id: correlationId,
      nonce: nonce,
      action: action,
      target_tab: targetTab,
      allocated_id: (outcome && outcome.allocated_id) || '',
      record: (outcome && outcome.record) || {}
    });

  } catch (err) {
    const errMsg = err && err.message ? err.message : String(err);
    if (businessWriteAttempted) {
      return ksBridgeJson_({
        status: 'RECOVERY_REQUIRED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        allocated_id: (outcome && outcome.allocated_id) || '',
        error_code: 'BRIDGE_POST_WRITE_FAILURE',
        message: 'Governed write encountered a post-mutation failure (audit/allocation/flush); quarantined for reconciliation: ' + errMsg,
        http_status: 409,
        retryable: false
      });
    }
    return ksBridgeJson_({
      status: 'REJECTED',
      correlation_id: correlationId,
      nonce: nonce,
      action: action,
      target_tab: targetTab,
      error_code: 'BRIDGE_EXECUTION_ERROR',
      message: errMsg,
      http_status: 500,
      retryable: false
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
 * Appends or updates a row in `targetTab` strictly by matching Row-1 header names,
 * flushes, and performs authoritative read-back verification before returning (Stage 1 W5).
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
  const nonceColIdx = headers.indexOf('nonce');

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
  } else {
    targetRow = sh.getLastRow() + 1;
    const newRow = headers.map(h => (h in flatData && flatData[h] !== undefined) ? flatData[h] : '');
    sh.getRange(targetRow, 1, 1, lastCol).setValues([newRow]);
  }

  // Mandatory flush & authoritative read-back verification (POL-003 / Section 11.2)
  SpreadsheetApp.flush();
  const readBack = sh.getRange(targetRow, 1, 1, lastCol).getValues()[0];
  if (idColIdx !== -1 && allocatedId) {
    const actualId = String(readBack[idColIdx] || '').trim();
    if (actualId !== allocatedId) {
      throw new Error(
        'READBACK_VERIFICATION_FAILED: Primary key mismatch in "' + targetTab + '" row ' + targetRow +
        ' (expected "' + allocatedId + '", read "' + actualId + '").'
      );
    }
  }
  if (nonceColIdx !== -1 && nonce) {
    const actualNonce = String(readBack[nonceColIdx] || '').trim();
    if (actualNonce !== nonce) {
      throw new Error(
        'READBACK_VERIFICATION_FAILED: Nonce mismatch in "' + targetTab + '" row ' + targetRow +
        ' (expected "' + nonce + '", read "' + actualNonce + '").'
      );
    }
  }

  const savedObj = {};
  headers.forEach((h, idx) => { savedObj[h] = readBack[idx]; });
  return { allocated_id: allocatedId, record: savedObj };
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

/**
 * Records a bridge nonce allocation using monotonic 7-digit ALLOC-0000001 numbering
 * (never Date.now() epoch timestamps) with flush + read-back verification (Stage 1 W6).
 */
function ksRecordIdAllocation_(nonce, tabName, allocatedId) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName('IdAllocations');
  if (!sh || sh.getLastColumn() < 1) {
    throw new Error('ID_ALLOCATIONS_TAB_MISSING: IdAllocations sheet is required for governed bridge writes.');
  }
  const lastCol = sh.getLastColumn();
  const headers = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim());
  const allocColIdx = headers.indexOf('allocation_id');
  const nonceColIdx = headers.indexOf('nonce') !== -1 ? headers.indexOf('nonce') : headers.indexOf('idempotency_key');

  let maxAllocSeq = 0;
  const lastRow = sh.getLastRow();
  if (allocColIdx !== -1 && lastRow >= 2) {
    const existingIds = sh.getRange(2, allocColIdx + 1, lastRow - 1, 1).getValues();
    for (let i = 0; i < existingIds.length; i++) {
      // Ignore any legacy >9-digit epoch timestamps while preserving monotonic 7-digit sequences
      const m = String(existingIds[i][0] || '').trim().match(/^ALLOC-(\d{1,9})$/);
      if (m) {
        maxAllocSeq = Math.max(maxAllocSeq, parseInt(m[1], 10));
      }
    }
  }

  const nextAllocId = 'ALLOC-' + String(maxAllocSeq + 1).padStart(7, '0');
  const nowIso = typeof ksNowIso_ === 'function' ? ksNowIso_() : new Date().toISOString();
  const row = headers.map(h => {
    if (h === 'allocation_id') return nextAllocId;
    if (h === 'tab_name' || h === 'target_table') return tabName;
    if (h === 'allocated_id') return allocatedId;
    if (h === 'nonce' || h === 'idempotency_key') return nonce;
    if (h === 'created_at') return nowIso;
    return '';
  });

  const targetRow = lastRow + 1;
  sh.getRange(targetRow, 1, 1, lastCol).setValues([row]);
  SpreadsheetApp.flush();

  const readBack = sh.getRange(targetRow, 1, 1, lastCol).getValues()[0];
  if (allocColIdx !== -1 && String(readBack[allocColIdx] || '').trim() !== nextAllocId) {
    throw new Error('ID_ALLOCATION_READBACK_FAILED: Expected ' + nextAllocId + ' in IdAllocations row ' + targetRow + '.');
  }
  if (nonceColIdx !== -1 && String(readBack[nonceColIdx] || '').trim() !== String(nonce).trim()) {
    throw new Error('ID_ALLOCATION_READBACK_FAILED: Nonce mismatch in IdAllocations row ' + targetRow + '.');
  }
  return { allocation_id: nextAllocId, row: targetRow };
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