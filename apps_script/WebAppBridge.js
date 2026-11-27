/**
 * KAWAD SWAD ERP - SIGNED WEB APP BRIDGE (WebAppBridge.gs)
 * Matches backend/app/apps_script_bridge.py & backend/app/action_registry.py (Phase 1.8+ / KS-RELEASE-02)
 *
 * Security Guarantees (W1–W6):
 *  - Mandatory HMAC-SHA256 + contract_version="2.0" + +/-300s skew check via ksVerifySignedBridgeEnvelope_.
 *  - W1: Uninterrupted ScriptLock ownership, strict lock-preserving ksLogAuditStrictLocked_ (no silent swallow),
 *        and attributable ExceptionRegister quarantine (RECOVERY_REQUIRED, HTTP 409) on post-mutation failure.
 *  - W2: Full nonce idempotency bound to (nonce, target_tab, action, actor_user_id, payload_hash).
 *  - W3: Strict 1:1 action -> canonical target_tab binding, immutable governance/control/scratch tab blocking,
 *        and privilege-sensitive role enforcement (AUDITOR blocked from all writes; SystemConfig blocked).
 *  - W4: Authoritative actor verification against Google Sheets Users tab (existence, active flag, role match).
 *  - W5: Full-row authoritative read-back verification after flush with audited failure quarantine.
 *  - W6: Monotonic 7-digit ALLOC-0000001 numbering ignoring legacy 13-digit epoch timestamps.
 */

const KS_BRIDGE_PROTECTED_GOVERNANCE_TABS = Object.freeze({
  AuditLog: true,
  IdAllocations: true,
  ExceptionRegister: true
});

const KS_BRIDGE_PROTECTED_CONTROL_TABS = Object.freeze({
  SystemConfig: true,
  BackupRegister: true,
  DBV5_FIELD_DICTIONARY_3074: true,
  START_HERE: true
});

const KS_BRIDGE_FORBIDDEN_SCRATCH_RE = /^(?:KS_P1_|KS_P2_|KS_P3_|DBV5_|DB_)/i;

const KS_BRIDGE_AUTH_USERS_ALLOWED_ACTIONS = Object.freeze({
  REVOKE_USER_SESSIONS: true,
  CHANGE_PASSWORD: true,
  RESET_PASSWORD: true
});

const KS_BRIDGE_ROLE_ALIASES = Object.freeze({
  OWNER_ADMIN: 'OWNER_ADMIN',
  OWNER: 'OWNER_ADMIN',
  ADMIN: 'OWNER_ADMIN',
  PA: 'PA',
  PERSONAL_ASSISTANT: 'PA',
  MANAGER: 'PA',
  OPERATIONS_MANAGER: 'PA',
  ACCOUNTS: 'ACCOUNTS',
  ACCOUNTANT: 'ACCOUNTS',
  FINANCE: 'ACCOUNTS',
  PROCUREMENT: 'PROCUREMENT',
  PURCHASE: 'PROCUREMENT',
  STORE: 'STORE',
  STOREKEEPER: 'STORE',
  WAREHOUSE: 'STORE',
  DISPATCH: 'STORE',
  PRODUCTION: 'PRODUCTION',
  FACTORY_WORKER: 'PRODUCTION',
  PRODUCTION_WORKER: 'PRODUCTION',
  WORKER: 'PRODUCTION',
  OPERATOR: 'PRODUCTION',
  LABOUR_SUPERVISOR: 'PRODUCTION',
  SUPERVISOR: 'PRODUCTION',
  QUALITY: 'QUALITY',
  QC: 'QUALITY',
  PACKAGING: 'PACKAGING',
  PACKING: 'PACKAGING',
  SALES: 'SALES',
  FIELD_SALESMAN: 'FIELD_SALESMAN',
  SALESMAN: 'FIELD_SALESMAN',
  HR: 'HR',
  AUDITOR: 'AUDITOR'
});

// Strict canonical action -> target_tab binding matching backend/app/action_registry.py (128 actions)
// plus Blueprint v2 Apps Script domain engine actions.
const KS_BRIDGE_ACTION_TARGET_TAB_MAP = Object.freeze({
  ACCEPT_VAN_LOADING_PASS: 'VanLoadingPasses',
  ADJUST_FINISHED_GOODS_STOCK: 'ProductionStockLedger',
  ADJUST_RAW_MATERIAL_STOCK: 'RawMaterialLedger',
  APPLY_SUPPLIER_ADVANCE: 'SupplierPayments',
  APPROVE_AND_EXECUTE_REQUEST: 'ApprovalRequests',
  APPROVE_PACKAGING_DISCREPANCY: 'PackagingBatches',
  APPROVE_PAYROLL: 'PayrollRuns',
  APPROVE_PRODUCTION_BATCH: 'ProductionBatches',
  APPROVE_RECIPE_VERSION: 'Recipes',
  APPROVE_SALARY_INCENTIVE: 'SalaryIncentives',
  ASSIGN_TASK: 'WorkAssignments',
  BOOTSTRAP_FIRST_OWNER: 'Users',
  BULK_LABOUR_ATTENDANCE: 'LabourAttendance',
  CALCULATE_PAYROLL: 'PayrollRuns',
  CANCEL_APPROVAL_REQUEST: 'ApprovalRequests',
  CANCEL_PURCHASE_ORDER: 'PurchaseOrders',
  CANCEL_SALE: 'Sales',
  CANCEL_VAN_LOADING_PASS: 'VanLoadingPasses',
  CHANGE_PASSWORD: 'AuthUsers',
  CHECK_IN_ATTENDANCE: 'EmployeeAttendance',
  CHECK_OUT_ATTENDANCE: 'EmployeeAttendance',
  CLOSE_ACCOUNTING_PERIOD: ['AccountingPeriods', 'FinancialPeriods'],
  CLOSE_COMPLAINT: 'ComplaintsRecalls',
  CONFIRM_SALES_ORDER: 'Sales',
  CONSUME_CREDIT_APPROVAL: 'ApprovalRequests',
  CORRECT_WORKER_ATTENDANCE: 'WorkerAttendance',
  CREATE_APPROVAL_REQUEST: 'ApprovalRequests',
  CREATE_COMPLAINT_OR_RECALL: 'ComplaintsRecalls',
  CREATE_CUSTOMER: 'Customers',
  CREATE_CUSTOMER_RETURN: 'CustomerReturns',
  CREATE_CUSTOM_ROLE: 'CustomRoles',
  CREATE_GOODS_RECEIPT: 'GoodsReceipts',
  CREATE_LABOUR: 'LabourMaster',
  CREATE_LEGACY_SALES_ORDER: 'Sales',
  CREATE_MILESTONE: 'FreelancerMilestones',
  CREATE_PRODUCT: 'Products',
  CREATE_PRODUCTION_BATCH: 'ProductionBatches',
  CREATE_PRODUCTION_ORDER: 'ProductionOrders',
  CREATE_PRODUCT_LOT: 'ProductLots',
  CREATE_PROJECT: 'FreelancerProjects',
  CREATE_PURCHASE_ORDER: 'PurchaseOrders',
  CREATE_QUALITY_CHECK: 'QualityChecks',
  CREATE_RAW_MATERIAL_MASTER: 'RawMaterials',
  CREATE_RECIPE: 'Recipes',
  CREATE_SALARY_INCENTIVE: 'SalaryIncentives',
  CREATE_SALE: 'Sales',
  CREATE_SALES_INVOICE: ['Sales', 'SalesInvoices'],
  CREATE_SALES_ORDER: 'SalesOrders',
  CREATE_SUPPLIER: 'Suppliers',
  CREATE_SUPPLIER_RETURN: 'SupplierReturns',
  CREATE_USER: 'Users',
  CREATE_VAN_LOADING_PASS: 'VanLoadingPasses',
  CREATE_WORKER: 'Workers',
  CREATE_WORK_ENTRY: 'LabourWorkEntries',
  DEACTIVATE_USER: 'Users',
  DELETE_CUSTOM_ROLE: 'CustomRoles',
  DISBURSE_APPROVED_ADVANCE: 'EmployeeAdvances',
  ISSUE_RAW_MATERIALS: 'RawMaterialLedger',
  LOG_SHOP_VISIT: 'ShopVisits',
  MARK_SALE_COMPLETE: 'Sales',
  PAY_GIG_WORK_ENTRY: 'LabourWorkEntries',
  PAY_SALARY_INCENTIVE: 'SalaryIncentives',
  POST_JOURNAL_VOUCHER: ['JournalHeaders', 'JournalEntries'],
  PRODUCTION_STOCK_DISPATCH: 'ProductionDispatches',
  QUALITY_CHECK_DECISION: ['QualityChecks', 'IncomingQualityChecks', 'InProcessQualityChecks', 'FinishedGoodsQualityChecks'],
  REACTIVATE_USER: 'Users',
  RECEIVE_GOODS: 'GoodsReceipts',
  RECEIVE_RAW_MATERIAL: ['RawMaterialLedger', 'InventoryLots'],
  RECONCILE_DISPATCH: 'ProductionDispatches',
  RECONCILE_FACTORY_STOCK: 'ProductionStockLedger',
  RECONCILE_PACKAGING_BATCH: 'PackagingBatches',
  RECONCILE_ROLE_ALIAS: 'Users',
  RECONCILE_SALESMAN_STOCK: 'SalesmanStockLedger',
  RECONCILE_WAREHOUSE_STOCK: 'SalesmanStockLedger',
  RECORD_ASSET_MAINTENANCE: 'AssetsMaintenance',
  RECORD_BULK_WORKER_ATTENDANCE: 'WorkerAttendance',
  RECORD_COMPLIANCE_ITEM: 'ComplianceRecords',
  RECORD_CUSTOMER_PAYMENT: ['CustomerPayments', 'Payments'],
  RECORD_DISTRIBUTION_DISPATCH: 'ProductionDispatches',
  RECORD_MARKETPLACE_SETTLEMENT: 'MarketplaceSettlements',
  RECORD_MATERIAL_CONSUMPTION: 'MaterialConsumption',
  RECORD_MILLING_BATCH: 'MillingBatches',
  RECORD_PACKAGING_BATCH: ['PackagingBatches', 'PackagingOutputs'],
  RECORD_PACKAGING_PENDING_REVIEW: 'PackagingBatches',
  RECORD_PRODUCTION_OUTPUT: 'ProductionOutputs',
  RECORD_SALE_PAYMENT: 'Payments',
  RECORD_STOCK_MOVEMENT: 'SalesmanStockLedger',
  RECORD_SUPPLIER_BILL: 'SupplierBills',
  RECORD_SUPPLIER_PAYMENT: 'SupplierPayments',
  RECORD_WORKER_ATTENDANCE: 'WorkerAttendance',
  RECORD_WORKFORCE_PAYMENT: 'WorkforcePayments',
  RECOVER_MILLING_BATCH: 'RawMaterialLedger',
  RECOVER_PACKAGING: 'PackagingBatches',
  RECOVER_RAW_MATERIALS_STATUS: 'ProductionBatches',
  REJECT_APPROVAL_REQUEST: 'ApprovalRequests',
  REJECT_PRODUCTION_BATCH: 'ProductionBatches',
  RELEASE_CREDIT_APPROVAL: 'ApprovalRequests',
  REMOVE_DUPLICATE_ATTENDANCE: 'WorkerAttendance',
  REPORT_VAN_LOADING_DISCREPANCY: 'VanLoadingPasses',
  REQUEST_STOCK_ADJUSTMENT: 'StockDiscrepancies',
  RESERVE_CREDIT_APPROVAL: 'ApprovalRequests',
  RESET_PASSWORD: 'AuthUsers',
  RESOLVE_LEGACY_BATCH_COST: 'ProductionBatches',
  RESUME_SALE: 'Sales',
  REVERSE_JOURNAL_VOUCHER: 'JournalHeaders',
  REVIEW_DAILY_CLOSING: 'DailyClosing',
  REVIEW_EXPENSE: 'Expenses',
  REVIEW_MILESTONE: 'FreelancerMilestones',
  REVIEW_STOCK_DISCREPANCY: 'StockDiscrepancies',
  REVIEW_TASK: 'WorkAssignments',
  REVOKE_TOKEN: 'RevokedTokens',
  REVOKE_USER_SESSIONS: 'AuthUsers',
  SUBMIT_DAILY_CLOSING: 'DailyClosing',
  SUBMIT_EXPENSE: 'Expenses',
  SUBMIT_GIG_WORK_ENTRY: 'LabourWorkEntries',
  SUBMIT_MILESTONE: 'FreelancerMilestones',
  SUBMIT_STOCK_DISCREPANCY: 'StockDiscrepancies',
  SUBMIT_TASK: 'WorkAssignments',
  UPDATE_CA_POLICY: 'Settings',
  UPDATE_CUSTOMER: 'Customers',
  UPDATE_CUSTOM_ROLE: 'CustomRoles',
  UPDATE_LABOUR: 'LabourMaster',
  UPDATE_LOT_STATUS: 'ProductLots',
  UPDATE_PAYROLL_ITEM: 'PayrollItems',
  UPDATE_PRODUCT: 'Products',
  UPDATE_RAW_MATERIAL_RATE: 'RawMaterials',
  UPDATE_SELF_PROFILE: 'Users',
  UPDATE_SUPPLIER: 'Suppliers',
  UPDATE_TASK: 'WorkAssignments',
  UPDATE_USER: 'Users',
  UPSERT_SALARY_STRUCTURE: 'SalaryStructures',
  VERIFY_GIG_WORK_ENTRY: 'LabourWorkEntries',
  VERIFY_RAW_MATERIAL_OPENING_STOCK: 'RawMaterialLedger'
});

// Privilege-sensitive table role gates enforced inside Apps Script (defense-in-depth W3)
const KS_BRIDGE_RESTRICTED_TAB_ROLES = Object.freeze({
  CustomRoles: ['OWNER_ADMIN'],
  Settings: ['OWNER_ADMIN'],
  SalaryStructures: ['OWNER_ADMIN'],
  AccountingPeriods: ['OWNER_ADMIN', 'ACCOUNTS'],
  FinancialPeriods: ['OWNER_ADMIN', 'ACCOUNTS'],
  PayrollRuns: ['OWNER_ADMIN', 'ACCOUNTS', 'PA', 'HR'],
  PayrollItems: ['OWNER_ADMIN', 'ACCOUNTS', 'PA', 'HR']
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
  // Canonical Blueprint v2 Apps Script engine target tabs (non-governance, non-control)
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
  Warehouses: true,
  BankTransactions: true,
  CreditNotes: true
});

function ksCanonicalizeBridgeRole_(rawRole) {
  const norm = String(rawRole || '').trim().toUpperCase();
  if (!norm) return '';
  if (Object.prototype.hasOwnProperty.call(KS_BRIDGE_ROLE_ALIASES, norm)) {
    return KS_BRIDGE_ROLE_ALIASES[norm];
  }
  return norm;
}

/**
 * Fail-closed target-table allowlist, action->tab binding, governance/control/scratch guard,
 * and privilege-sensitive role authorization (Stage 5 W3).
 */
function ksValidateBridgeTargetTab_(action, targetTab, actorRole, actorUserId, payload) {
  if (Object.prototype.hasOwnProperty.call(KS_BRIDGE_PROTECTED_GOVERNANCE_TABS, targetTab)) {
    return {
      ok: false,
      error_code: 'GOVERNANCE_TAB_WRITE_FORBIDDEN',
      http_status: 403,
      message: 'Direct bridge mutation of immutable governance tab "' + targetTab + '" is forbidden.'
    };
  }
  if (Object.prototype.hasOwnProperty.call(KS_BRIDGE_PROTECTED_CONTROL_TABS, targetTab)) {
    return {
      ok: false,
      error_code: 'CONTROL_TABLE_WRITE_FORBIDDEN',
      http_status: 403,
      message: 'Direct generic bridge mutation of protected control table "' + targetTab + '" is forbidden.'
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

  // Enforce strict registered action -> target_tab binding (prevents caller-controlled routing mismatch)
  if (!Object.prototype.hasOwnProperty.call(KS_BRIDGE_ACTION_TARGET_TAB_MAP, action)) {
    return {
      ok: false,
      error_code: 'UNREGISTERED_BRIDGE_ACTION',
      http_status: 403,
      message: 'Action "' + action + '" is not registered in the governed bridge action allowlist.'
    };
  }
  const boundTabs = KS_BRIDGE_ACTION_TARGET_TAB_MAP[action];
  const allowedList = Array.isArray(boundTabs) ? boundTabs : [boundTabs];
  if (allowedList.indexOf(targetTab) === -1) {
    return {
      ok: false,
      error_code: 'ACTION_TARGET_TAB_MISMATCH',
      http_status: 403,
      message: 'Action "' + action + '" is bound to [' + allowedList.join(', ') + '] and cannot target "' + targetTab + '".'
    };
  }

  // Enforce canonical role restrictions (AUDITOR read-only + privilege-sensitive tables)
  const canonicalRole = ksCanonicalizeBridgeRole_(actorRole);
  if (canonicalRole === 'AUDITOR') {
    return {
      ok: false,
      error_code: 'AUDITOR_WRITE_FORBIDDEN',
      http_status: 403,
      message: 'AUDITOR role is strictly read-only and forbidden from executing governed bridge writes.'
    };
  }

  const p = payload && typeof payload === 'object' ? payload : {};
  const targetUserId = String(p.user_id || (p.record && p.record.user_id) || (p.updates && p.updates.user_id) || '').trim();

  if (targetTab === 'Users') {
    if (action === 'UPDATE_SELF_PROFILE') {
      if (!targetUserId || targetUserId !== actorUserId) {
        return {
          ok: false,
          error_code: 'SELF_PROFILE_TARGET_MISMATCH',
          http_status: 403,
          message: 'UPDATE_SELF_PROFILE may only update the authenticated actor\'s own Users record.'
        };
      }
    } else if (canonicalRole !== 'OWNER_ADMIN') {
      return {
        ok: false,
        error_code: 'INSUFFICIENT_ROLE_FOR_TARGET_TAB',
        http_status: 403,
        message: 'Role "' + canonicalRole + '" is not authorized to mutate Users via "' + action + '".'
      };
    }
  }

  if (targetTab === 'AuthUsers') {
    if (action === 'CHANGE_PASSWORD') {
      if (canonicalRole !== 'OWNER_ADMIN' && (!targetUserId || targetUserId !== actorUserId)) {
        return {
          ok: false,
          error_code: 'INSUFFICIENT_ROLE_FOR_AUTH_USERS',
          http_status: 403,
          message: 'Non-owner actor "' + actorUserId + '" may only change their own password.'
        };
      }
    } else if (canonicalRole !== 'OWNER_ADMIN') {
      return {
        ok: false,
        error_code: 'INSUFFICIENT_ROLE_FOR_AUTH_USERS',
        http_status: 403,
        message: 'Role "' + canonicalRole + '" is not authorized for "' + action + '" on AuthUsers.'
      };
    }
  }

  if (Object.prototype.hasOwnProperty.call(KS_BRIDGE_RESTRICTED_TAB_ROLES, targetTab)) {
    const allowedRoles = KS_BRIDGE_RESTRICTED_TAB_ROLES[targetTab];
    if (allowedRoles.indexOf(canonicalRole) === -1) {
      return {
        ok: false,
        error_code: 'INSUFFICIENT_ROLE_FOR_TARGET_TAB',
        http_status: 403,
        message: 'Role "' + canonicalRole + '" is not authorized to write to "' + targetTab + '".'
      };
    }
  }

  return { ok: true, canonical_role: canonicalRole };
}

/**
 * Authoritatively verifies actor_user_id and actor_role against Google Sheets `Users` tab (Stage 5 W4).
 * Rejects uninitialized user directories, unknown/forged actor IDs, inactive users, and role escalation.
 */
function ksVerifyBridgeActor_(actorUserId, actorRole) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    return {
      ok: false,
      error_code: 'ACTOR_DIRECTORY_UNAVAILABLE',
      http_status: 503,
      message: 'Active spreadsheet is unavailable for authoritative actor verification.'
    };
  }
  const userSheet = ss.getSheetByName((typeof KS_CONFIG !== 'undefined' && KS_CONFIG.TABS && KS_CONFIG.TABS.USERS) || 'Users');
  if (!userSheet || userSheet.getLastRow() < 2) {
    return {
      ok: false,
      error_code: 'ACTOR_DIRECTORY_UNINITIALIZED',
      http_status: 403,
      message: 'Users directory is missing or empty; complete First-Owner bootstrap before governed writes.'
    };
  }

  const lastCol = userSheet.getLastColumn();
  if (lastCol < 1) {
    return {
      ok: false,
      error_code: 'ACTOR_DIRECTORY_INVALID_SCHEMA',
      http_status: 503,
      message: 'Users directory has no header row.'
    };
  }
  const data = userSheet.getRange(1, 1, userSheet.getLastRow(), lastCol).getValues();
  const headers = data[0].map(h => String(h || '').trim());
  const uidIdx = headers.indexOf('user_id');
  const roleIdx = headers.indexOf('role') !== -1
    ? headers.indexOf('role')
    : (headers.indexOf('user_role') !== -1 ? headers.indexOf('user_role') : headers.indexOf('role_code'));
  const activeIdx = headers.indexOf('active') !== -1
    ? headers.indexOf('active')
    : (headers.indexOf('is_active') !== -1 ? headers.indexOf('is_active') : headers.indexOf('status'));

  if (uidIdx === -1 || roleIdx === -1) {
    return {
      ok: false,
      error_code: 'ACTOR_DIRECTORY_INVALID_SCHEMA',
      http_status: 503,
      message: 'Users directory must contain user_id and role headers.'
    };
  }

  const claimedRole = ksCanonicalizeBridgeRole_(actorRole);
  for (let i = 1; i < data.length; i++) {
    const rowUid = String(data[i][uidIdx] || '').trim();
    if (rowUid === actorUserId) {
      const rawActive = activeIdx !== -1 ? String(data[i][activeIdx]).trim().toUpperCase() : 'TRUE';
      const isActive = (rawActive === 'TRUE' || rawActive === 'YES' || rawActive === 'ACTIVE' || rawActive === '1');
      if (!isActive) {
        return {
          ok: false,
          error_code: 'ACTOR_INACTIVE',
          http_status: 403,
          message: 'Actor "' + actorUserId + '" is inactive/deactivated in Users directory.'
        };
      }
      const authoritativeRole = ksCanonicalizeBridgeRole_(data[i][roleIdx]);
      if (!authoritativeRole) {
        return {
          ok: false,
          error_code: 'ACTOR_ROLE_MISSING',
          http_status: 403,
          message: 'Authoritative role is missing for actor "' + actorUserId + '" in Users directory.'
        };
      }
      if (authoritativeRole === 'AUDITOR') {
        return {
          ok: false,
          error_code: 'AUDITOR_WRITE_FORBIDDEN',
          http_status: 403,
          message: 'Actor "' + actorUserId + '" holds read-only AUDITOR role in Users directory.'
        };
      }
      if (authoritativeRole !== claimedRole) {
        return {
          ok: false,
          error_code: 'ACTOR_ROLE_MISMATCH',
          http_status: 403,
          message: 'Claimed actor_role "' + claimedRole + '" does not match authoritative Users role "' + authoritativeRole + '" for "' + actorUserId + '".'
        };
      }
      return {
        ok: true,
        user_id: actorUserId,
        canonical_role: authoritativeRole
      };
    }
  }

  return {
    ok: false,
    error_code: 'ACTOR_NOT_FOUND',
    http_status: 403,
    message: 'Actor "' + actorUserId + '" does not exist in authoritative Users directory.'
  };
}

function ksNormalizeReadbackVal_(val) {
  if (val === undefined || val === null) return '';
  if (typeof val === 'boolean') return val ? 'true' : 'false';
  if (val instanceof Date) return val.toISOString();
  const s = String(val).trim();
  const lower = s.toLowerCase();
  if (lower === 'true' || lower === 'false') return lower;
  return s;
}

/**
 * Looks up AuditLog replay binding metadata (action, actor_user_id, payload_hash) for a nonce (Stage 5 W2).
 */
function ksFindAuditReplayMetadata_(nonce, allocatedId) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) return null;
  const auditTab = (typeof KS_CONFIG !== 'undefined' && KS_CONFIG.TABS && KS_CONFIG.TABS.AUDIT_LOG) || 'AuditLog';
  const sh = ss.getSheetByName(auditTab);
  if (!sh || sh.getLastRow() < 2) return null;
  const data = sh.getDataRange().getValues();
  const headers = data[0].map(h => String(h || '').trim());
  const actionIdx = headers.indexOf('action');
  const actorIdx = headers.indexOf('actor_user_id');
  const newValIdx = headers.indexOf('new_value');
  const relIdx = headers.indexOf('related_record_id');
  const entIdIdx = headers.indexOf('entity_id');
  const nonceNeedle = 'nonce=' + nonce;

  for (let i = data.length - 1; i >= 1; i--) {
    const newVal = newValIdx !== -1 ? String(data[i][newValIdx] || '') : '';
    const relVal = relIdx !== -1 ? String(data[i][relIdx] || '').trim() : '';
    const entVal = entIdIdx !== -1 ? String(data[i][entIdIdx] || '').trim() : '';
    if (relVal === nonce || newVal.indexOf(nonceNeedle) !== -1 || (allocatedId && entVal === allocatedId && newVal.indexOf('CONFIRMED') !== -1)) {
      const hashMatch = newVal.match(/hash=([0-9a-fA-F]{16,128})/);
      return {
        action: actionIdx !== -1 ? String(data[i][actionIdx] || '').trim().toUpperCase() : '',
        actor_user_id: actorIdx !== -1 ? String(data[i][actorIdx] || '').trim() : '',
        payload_hash: hashMatch ? hashMatch[1].toLowerCase() : ''
      };
    }
  }
  return null;
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  let action = '';
  let targetTab = '';
  let nonce = '';
  let correlationId = '';
  let actorUserId = '';
  let actorRole = '';
  let payloadHash = '';
  let businessWriteAttempted = false;
  let outcome = null;

  try {
    // 1. Mandatory HMAC-SHA256 + contract_version="2.0" + +/-300s skew verification
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
    actorUserId = String(req.actor_user_id || '').trim();
    actorRole = String(req.actor_role || '').trim().toUpperCase();
    payloadHash = String(req.payload_hash || '').trim().toLowerCase();
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

    // 1C. Fail-closed target-table allowlist, action->tab binding, governance/control/scratch & role guard (W3)
    const tabCheck = ksValidateBridgeTargetTab_(action, targetTab, actorRole, actorUserId, payload);
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

    // 1D. Fail-closed check: strict lock-preserving audit logger MUST be loaded (no silent fallback)
    if (typeof ksLogAuditStrictLocked_ !== 'function') {
      return ksBridgeJson_({
        status: 'REJECTED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        error_code: 'MANDATORY_AUDIT_LOGGER_MISSING',
        message: 'Mandatory strict lock-preserving ksLogAuditStrictLocked_ is not loaded in Apps Script project.',
        http_status: 503,
        retryable: false
      });
    }

    // 2. Serialize via ScriptLock
    lock.waitLock(20000);

    // 2A. Authoritative Actor Verification against Users directory (W4)
    const actorCheck = ksVerifyBridgeActor_(actorUserId, actorRole);
    if (!actorCheck.ok) {
      return ksBridgeJson_({
        status: 'REJECTED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        error_code: actorCheck.error_code,
        message: actorCheck.message,
        http_status: actorCheck.http_status,
        retryable: false
      });
    }

    // 2B. Enforce Nonce + Target-Tab + Action + Actor + Payload-Hash Idempotency (W2)
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
      const auditMeta = ksFindAuditReplayMetadata_(nonce, existing.allocated_id);
      if (auditMeta) {
        if (auditMeta.action && auditMeta.action !== action) {
          return ksBridgeJson_({
            status: 'REJECTED',
            correlation_id: correlationId,
            nonce: nonce,
            action: action,
            target_tab: targetTab,
            error_code: 'NONCE_ACTION_CONFLICT',
            message: 'Nonce "' + nonce + '" is already bound to action "' + auditMeta.action + '", cannot replay as "' + action + '".',
            http_status: 409,
            retryable: false
          });
        }
        if (auditMeta.actor_user_id && auditMeta.actor_user_id !== actorUserId) {
          return ksBridgeJson_({
            status: 'REJECTED',
            correlation_id: correlationId,
            nonce: nonce,
            action: action,
            target_tab: targetTab,
            error_code: 'NONCE_ACTOR_CONFLICT',
            message: 'Nonce "' + nonce + '" is already bound to a different actor; cross-actor replay rejected.',
            http_status: 409,
            retryable: false
          });
        }
        if (auditMeta.payload_hash && payloadHash && auditMeta.payload_hash !== payloadHash) {
          return ksBridgeJson_({
            status: 'REJECTED',
            correlation_id: correlationId,
            nonce: nonce,
            action: action,
            target_tab: targetTab,
            error_code: 'NONCE_PAYLOAD_HASH_CONFLICT',
            message: 'Nonce "' + nonce + '" was previously executed with a different payload_hash; mutated replay rejected.',
            http_status: 409,
            retryable: false
          });
        }
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

    // 3. Execute Governed Domain Action (or Header-Mapped Canonical Table Write with Full Read-Back)
    businessWriteAttempted = true;
    outcome = ksRouteGovernedWrite_(action, targetTab, payload, actorUserId, actorCheck.canonical_role, nonce, correlationId);

    // 4. Record Monotonic Nonce in IdAllocations & Write Strict Lock-Preserving AuditLog (W1/W2/W6)
    const finalAllocatedId = (outcome && outcome.allocated_id) || nonce;
    ksRecordIdAllocation_(nonce, targetTab, finalAllocatedId);

    const auditNewValue = 'CONFIRMED | nonce=' + nonce + ' | corr=' + correlationId + (payloadHash ? ' | hash=' + payloadHash : '');
    ksLogAuditStrictLocked_(action, targetTab, finalAllocatedId, {
      actor_user_id: actorUserId,
      field_changed: 'governed_write',
      old_value: '',
      new_value: auditNewValue,
      reason: 'FastAPI Bridge: ' + action,
      related_record_id: nonce,
      audit_nonce: 'AUD_BRIDGE_' + nonce,
      callerHoldsLock: true
    });

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
      // W1: Best-effort attributable forensic exception entry (lock-safe, never masks RECOVERY_REQUIRED)
      let recoveryExceptionId = '';
      try {
        if (typeof ksLogExceptionLocked_ === 'function' && lock.hasLock()) {
          const excRes = ksLogExceptionLocked_(
            'CRITICAL',
            'WebAppBridge.doPost',
            targetTab,
            (outcome && outcome.allocated_id) || nonce,
            errMsg,
            {
              recovery_action: 'MANUAL_RECONCILIATION_REQUIRED',
              action: action,
              target_tab: targetTab,
              nonce: nonce,
              correlation_id: correlationId,
              actor_user_id: actorUserId,
              actor_role: actorRole,
              allocated_id: (outcome && outcome.allocated_id) || ''
            }
          );
          if (excRes && excRes.exception_id) {
            recoveryExceptionId = excRes.exception_id;
          }
        }
      } catch (_excLogErr) {
        // Never mask RECOVERY_REQUIRED if secondary forensic logging fails
      }

      return ksBridgeJson_({
        status: 'RECOVERY_REQUIRED',
        correlation_id: correlationId,
        nonce: nonce,
        action: action,
        target_tab: targetTab,
        actor_user_id: actorUserId,
        allocated_id: (outcome && outcome.allocated_id) || '',
        recovery_exception_id: recoveryExceptionId,
        error_code: 'BRIDGE_POST_WRITE_FAILURE',
        message: 'Governed write encountered a post-mutation failure (readback/audit/allocation/flush); quarantined for Owner reconciliation: ' + errMsg,
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
 * Routes registered actions from backend/app/action_registry.py to specialized
 * Apps Script domain engines, falling back to safe Row-1 header-mapped sheet writes
 * with full-row authoritative read-back verification.
 */
function ksRouteGovernedWrite_(action, targetTab, payload, actorUserId, actorRole, nonce, correlationId) {
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

  return ksWriteCanonicalRowByHeaders_(targetTab, payload, actorUserId, nonce);
}

/**
 * Appends or updates a row in `targetTab` strictly by matching Row-1 header names,
 * flushes, and performs FULL authoritative field-by-field read-back verification (Stage 5 W5).
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
  const allocatedId = idField && flatData[idField] ? String(flatData[idField]).trim() : '';
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

  let expectedRow;
  if (targetRow !== -1) {
    const existingRow = sh.getRange(targetRow, 1, 1, lastCol).getValues()[0];
    expectedRow = headers.map((h, idx) => (h in flatData && flatData[h] !== undefined) ? flatData[h] : existingRow[idx]);
    sh.getRange(targetRow, 1, 1, lastCol).setValues([expectedRow]);
  } else {
    targetRow = sh.getLastRow() + 1;
    expectedRow = headers.map(h => (h in flatData && flatData[h] !== undefined) ? flatData[h] : '');
    sh.getRange(targetRow, 1, 1, lastCol).setValues([expectedRow]);
  }

  // Mandatory flush & FULL field-by-field authoritative read-back verification (POL-003 / Stage 5 W5)
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

  for (let idx = 0; idx < headers.length; idx++) {
    const colName = headers[idx];
    if (Object.prototype.hasOwnProperty.call(flatData, colName) && flatData[colName] !== undefined) {
      const expNorm = ksNormalizeReadbackVal_(expectedRow[idx]);
      const actNorm = ksNormalizeReadbackVal_(readBack[idx]);
      if (expNorm !== actNorm) {
        throw new Error(
          'READBACK_VERIFICATION_FAILED: Field "' + colName + '" mismatch in "' + targetTab + '" row ' + targetRow +
          ' (expected "' + expNorm + '", read "' + actNorm + '").'
        );
      }
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
 * (never Date.now() epoch timestamps) with flush + read-back verification (Stage 5 W6).
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