/**
 * KAWAD SWAD ERP - PHASE H LIVE-CUTOVER VERIFICATION, TAB HYGIENE & OWNER SIGN-OFF GATE
 * Blueprint Version: 2.0 | Enforces POL-017, POL-018, Section 11.7, Section 16.1, Section 17
 */

const KS_TRANSACTION_TABLES_TO_VERIFY_CLEAN = Object.freeze([
  'IdAllocations', 'ExceptionRegister',
  'PurchaseRequisitions', 'SupplierQuotations', 'IncomingQualityChecks',
  'InventoryLots', 'InventoryMovements', 'InventoryBalances', 'StockReservations',
  'StockTransfers', 'StockCounts', 'StockAdjustments', 'DamagedStock', 'ExpiredStock', 'QuarantineStock',
  'ProductionPlans', 'ProductionOrders', 'MaterialIssues', 'MaterialConsumption',
  'ProductionOutputs', 'ProcessLosses', 'ProductionWorkerEntries',
  'InProcessQualityChecks', 'FinishedGoodsQualityChecks', 'HoldReleaseRecords',
  'PackagingPlans', 'PackagingOutputs', 'PackagingLosses',
  'SalesOrders', 'SalesOrderItems', 'SalesInvoices', 'SalesInvoiceItems',
  'CustomerPayments', 'CustomerPaymentAllocations', 'SalesReturns', 'CreditNotes',
  'Shipments', 'ShipmentItems', 'DeliveryTracking',
  'JournalEntries', 'JournalEntryLines', 'GeneralLedger', 'BankTransactions',
  'LeaveRecords', 'OvertimeRecords', 'SalaryPayments', 'EmployeeAdvances'
]);

const KS_PROTECTED_SYSTEM_AND_REPORT_TABS = Object.freeze([
  'START_HERE',
  'DBV5_FIELD_DICTIONARY_3074',
  'IdAllocations',
  'AuditLog',
  'ExceptionRegister',
  'SystemConfig',
  'DocumentRegister',
  'BackupRegister',
  'RPT_TrialBalance',
  'RPT_StockStatus',
  'RPT_SalesAndReceivables',
  'RPT_PhaseH_ReleaseGate',
  'RPT_Section17_OpenDecisions'
]);

// Temporary build-phase scratch tabs safe to remove before Go-Live (never deletes DBV5_FIELD_DICTIONARY_3074)
const KS_LEGACY_SCRATCH_PREFIXES = Object.freeze([
  'KS_P1_',
  'KS_P2_',
  'KS_P3_',
  'DBV5_',
  'DB_'
]);

const KS_LEGACY_SCRATCH_EXACT_TABS = Object.freeze([
  'KS_SCHEMA_AUDIT',
  'KS_FIELD_MAPPING',
  'KS_OPEN_DECISIONS',
  'KS_DEPLOYMENT_LOG',
  'KS_FULL_AUDIT_EXPORT',
  'KS_DEPLOYMENT_AUDIT'
]);

function ksGetProtectedOfficialTabSet_() {
  const protectedSet = new Set(KS_PROTECTED_SYSTEM_AND_REPORT_TABS);

  if (typeof KS_CORE_TABLES !== 'undefined') {
    Object.keys(KS_CORE_TABLES).forEach(group => {
      (KS_CORE_TABLES[group] || []).forEach(t => protectedSet.add(t));
    });
  }
  if (typeof KS_WORKFORCE_TABLES !== 'undefined') {
    KS_WORKFORCE_TABLES.forEach(t => protectedSet.add(t));
  }
  KS_TRANSACTION_TABLES_TO_VERIFY_CLEAN.forEach(t => protectedSet.add(t));

  return protectedSet;
}

function ksIsLegacyScratchTab_(tabName, protectedSet) {
  if (protectedSet.has(tabName)) return false;
  if (KS_LEGACY_SCRATCH_EXACT_TABS.includes(tabName)) return true;
  return KS_LEGACY_SCRATCH_PREFIXES.some(prefix => tabName.startsWith(prefix));
}

/**
 * 1. Read-Only Audit of Legacy Build/Migration Scratch Tabs:
 * Categorizes all tabs into:
 *   - Protected Core ERP & Report Tabs (108)
 *   - Legacy Build/Audit Scratch Tabs (~46 -> recommended to clean)
 *   - Blueprint Domain Tables (147 -> official 218-table dictionary tables)
 */
function ksAuditUnwantedTabs() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksAuditUnwantedTabs');
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const protectedSet = ksGetProtectedOfficialTabSet_();

  const allSheets = ss.getSheets();
  const legacyScratchTabs = [];
  const blueprintDomainTabs = [];

  allSheets.forEach(sh => {
    const name = sh.getName();
    if (protectedSet.has(name)) return;
    if (ksIsLegacyScratchTab_(name, protectedSet)) {
      legacyScratchTabs.push(name);
    } else {
      blueprintDomainTabs.push(name);
    }
  });

  Logger.log('=== WORKBOOK TAB HYGIENE SUMMARY ===');
  Logger.log('Total tabs: ' + allSheets.length);
  Logger.log('1. Protected Active ERP & Report Tabs: ' + (allSheets.length - legacyScratchTabs.length - blueprintDomainTabs.length));
  Logger.log('2. Official Blueprint Domain Tables (218-table schema): ' + blueprintDomainTabs.length);
  Logger.log('3. Legacy Build/Audit Scratch Tabs to Clean (' + legacyScratchTabs.length + '): ' + JSON.stringify(legacyScratchTabs));

  return {
    checked_by: ctx.user_id,
    total_tabs: allSheets.length,
    legacy_scratch_count: legacyScratchTabs.length,
    legacy_scratch_tabs: legacyScratchTabs,
    blueprint_domain_count: blueprintDomainTabs.length
  };
}

/**
 * 2. One-Click Safe Cleaner for the 46 Legacy Build/Audit Scratch Tabs (POL-018).
 * Never touches any protected core tab, DBV5_FIELD_DICTIONARY_3074, or Blueprint domain table.
 */
function ksCleanAllLegacyScratchTabs() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksCleanAllLegacyScratchTabs');
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const protectedSet = ksGetProtectedOfficialTabSet_();

  const deleted = [];
  ss.getSheets().forEach(sh => {
    const name = sh.getName();
    if (ksIsLegacyScratchTab_(name, protectedSet)) {
      ss.deleteSheet(sh);
      deleted.push(name);
    }
  });

  SpreadsheetApp.flush();

  if (deleted.length > 0) {
    ksLogAudit_('LEGACY_SCRATCH_TABS_CLEANED', 'WORKBOOK', ss.getId(), {
      actor_user_id: ctx.user_id,
      field_changed: 'sheet_tabs',
      old_value: deleted.length + ' scratch tabs',
      new_value: 'DELETED',
      reason: 'Removed legacy build/migration scratch tabs while preserving DBV5_FIELD_DICTIONARY_3074 and all Blueprint tables (POL-018)',
      approved_by_user_id: ctx.user_id
    });
  }

  Logger.log('Successfully cleaned ' + deleted.length + ' legacy scratch tabs: ' + JSON.stringify(deleted));
  Logger.log('Remaining tabs in workbook: ' + ss.getSheets().length);
  return { success: true, deleted_count: deleted.length, remaining_tabs: ss.getSheets().length };
}

/**
 * 3. Protected Arbitrary Tab Deletion (if you ever want to remove specific extra tabs by name).
 */
function ksDeleteUnwantedTabs(tabNamesToDelete, confirmationPhrase) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksDeleteUnwantedTabs');
  if (confirmationPhrase !== 'DELETE_APPROVED_UNWANTED_TABS') {
    throw new Error('Safety Lock: Pass exact phrase "DELETE_APPROVED_UNWANTED_TABS" to delete tabs.');
  }
  if (!Array.isArray(tabNamesToDelete) || tabNamesToDelete.length === 0) {
    throw new Error('Provide an array of exact tab names to delete.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const protectedSet = ksGetProtectedOfficialTabSet_();
  const deleted = [];
  const skipped = [];

  tabNamesToDelete.forEach(rawName => {
    const name = String(rawName || '').trim();
    if (!name) return;

    if (protectedSet.has(name)) {
      skipped.push({ tab: name, reason: 'BLOCKED_PROTECTED_OFFICIAL_TAB' });
      return;
    }

    const sh = ss.getSheetByName(name);
    if (!sh) {
      skipped.push({ tab: name, reason: 'TAB_NOT_FOUND' });
      return;
    }

    ss.deleteSheet(sh);
    deleted.push(name);
  });

  SpreadsheetApp.flush();

  if (deleted.length > 0) {
    ksLogAudit_('UNWANTED_TABS_DELETED', 'WORKBOOK', ss.getId(), {
      actor_user_id: ctx.user_id,
      field_changed: 'sheet_tabs',
      old_value: deleted.join(', '),
      new_value: 'DELETED (' + deleted.length + ' tabs)',
      reason: 'Cleaned unwanted tabs prior to Phase H cutover (POL-018)',
      approved_by_user_id: ctx.user_id
    });
  }

  Logger.log('Deleted tabs (' + deleted.length + '): ' + JSON.stringify(deleted));
  return { success: true, deleted: deleted, skipped: skipped };
}

/**
 * 4. Read-only Phase H Pre-Go-Live Audit (POL-017).
 */
function ksVerifyCleanLiveBaseline() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksVerifyCleanLiveBaseline');
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  const dirtyTables = [];
  KS_TRANSACTION_TABLES_TO_VERIFY_CLEAN.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) {
      dirtyTables.push({ tab: tabName, issue: 'MISSING_TAB' });
      return;
    }
    const dataRows = Math.max(0, sh.getLastRow() - 1);
    if (dataRows > 0) {
      dirtyTables.push({ tab: tabName, issue: 'NON_EMPTY_ROWS=' + dataRows });
    }
  });

  const userSheet = ss.getSheetByName(KS_CONFIG.TABS.USERS);
  const activeUserRows = userSheet ? Math.max(0, userSheet.getLastRow() - 1) : 0;

  const isClean = (dirtyTables.length === 0);
  const report = {
    checked_at: ksNowIso_(),
    checked_by: ctx.user_id,
    clean_transaction_baseline: isClean,
    configured_users_count: activeUserRows,
    dirty_or_missing_tables: dirtyTables
  };

  Logger.log('=== PHASE H CLEAN BASELINE AUDIT ===');
  Logger.log(JSON.stringify(report, null, 2));
  return report;
}

/**
 * 5. Controlled Test-Data Purger for New Production Copy (POL-017 & POL-018).
 */
function ksPurgeTestRowsForCleanCutover(confirmationPhrase) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksPurgeTestRowsForCleanCutover');
  if (confirmationPhrase !== 'RESET_FOR_CLEAN_PRODUCTION_BASELINE') {
    throw new Error('Safety Lock: Pass exact phrase "RESET_FOR_CLEAN_PRODUCTION_BASELINE" to clear test rows.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let clearedTabs = 0;

  KS_TRANSACTION_TABLES_TO_VERIFY_CLEAN.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) return;
    const lastRow = sh.getLastRow();
    if (lastRow > 1) {
      sh.getRange(2, 1, lastRow - 1, sh.getLastColumn()).clearContent();
      clearedTabs++;
    }
  });

  ['RPT_TrialBalance', 'RPT_StockStatus', 'RPT_SalesAndReceivables'].forEach(rpt => {
    const rSh = ss.getSheetByName(rpt);
    if (rSh && rSh.getLastRow() > 1) {
      rSh.getRange(2, 1, rSh.getLastRow() - 1, rSh.getLastColumn()).clearContent();
    }
  });

  SpreadsheetApp.flush();

  ksLogAudit_('TEST_ROWS_PURGED_FOR_CUTOVER', 'WORKBOOK', ss.getId(), {
    actor_user_id: ctx.user_id,
    field_changed: 'transactional_rows',
    old_value: 'TEST_DATA',
    new_value: '0_ROWS_CLEAN_BASELINE',
    reason: 'Purged ' + clearedTabs + ' tables in new production copy per POL-017',
    approved_by_user_id: ctx.user_id
  });

  Logger.log('Purged test rows across ' + clearedTabs + ' tables.');
  return { success: true, cleared_tables: clearedTabs };
}

/**
 * 6. Generates Section 17 Owner & CA Open-Decisions Sign-Off Register tab.
 */
function ksGenerateSection17DecisionRegister() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN, KS_ROLES.PA], 'ksGenerateSection17DecisionRegister');
  const nowIso = ksNowIso_();

  const decisions = [
    ['DEC-01', 'Business & Legal', 'Confirm legal business name, address, and registration status (proprietorship/partnership/company)', 'OWNER_ADMIN', 'OPEN', ''],
    ['DEC-02', 'Business & Legal', 'Confirm active GST registration status, GSTIN, and GST filing scheme (Regular / Composition / Exempt)', 'OWNER_ADMIN / CA', 'OPEN', ''],
    ['DEC-03', 'Business & Legal', 'Confirm FSSAI license number(s), renewal dates, and factory/warehouse locations', 'OWNER_ADMIN', 'OPEN', ''],
    ['DEC-04', 'Locations & Warehouses', 'Confirm exact list of factories, warehouses, and storage locations', 'OWNER_ADMIN', 'OPEN', ''],
    ['DEC-05', 'Products & SKUs', 'Confirm complete product catalogue (Moong Master, Chana Masala, Jeera, etc.) & retail pack sizes (200g, 500g, 1000g)', 'OWNER_ADMIN', 'OPEN', ''],
    ['DEC-06', 'Products & SKUs', 'Confirm SKU barcodes/EAN codes, shelf-life days per SKU, and label version approval workflow', 'OWNER_ADMIN / QUALITY', 'OPEN', ''],
    ['DEC-07', 'Pricing & Channels', 'Confirm channel-wise price lists (Retail/Field, Distributor, Direct, Online) and credit limit rules', 'OWNER_ADMIN / SALES', 'OPEN', ''],
    ['DEC-08', 'Recipes & Manufacturing', 'Confirm approved recipe versions, standard input-output ratios, and acceptable process loss % thresholds', 'OWNER_ADMIN / PRODUCTION', 'OPEN', ''],
    ['DEC-09', 'Workforce & Payroll', 'Confirm Gig-Worker piece/hourly task rates and supervisor verification cutoff schedule', 'OWNER_ADMIN', 'OPEN', ''],
    ['DEC-10', 'Workforce & Payroll', 'Confirm Fixed-Employee monthly salary structures, overtime rates, and advance recovery rules', 'OWNER_ADMIN', 'OPEN', ''],
    ['DEC-11', 'Accounting & CA', 'Approve final Chart of Accounts codes and mapping for sales, purchases, labour, overheads, cash, and bank', 'CA / OWNER_ADMIN', 'OPEN', ''],
    ['DEC-12', 'Accounting & CA', 'Confirm HSN codes and exact CGST/SGST/IGST rates for each finished SKU and raw material', 'CA', 'OPEN', ''],
    ['DEC-13', 'Accounting & CA', 'Confirm inventory valuation method (FIFO vs Weighted Average) and monthly financial period closing cutoff', 'CA / OWNER_ADMIN', 'OPEN', ''],
    ['DEC-14', 'Opening Cutover', 'Approve verified Opening Stock lots (physical count) and Opening Cash/Bank/Receivable/Payable balances', 'OWNER_ADMIN / CA', 'OPEN', '']
  ];

  ksWriteReportView_(
    'RPT_Section17_OpenDecisions',
    'KAWAD SWAD ERP - SECTION 17 OWNER & CA SIGN-OFF REGISTER',
    [
      ['Blueprint Reference', 'Section 17 (47 Open Decisions Consolidated into 14 Sign-Off Gates)'],
      ['Generated At', nowIso + ' by ' + ctx.user_id],
      ['Rule (POL-016)', 'No tax rate, price, recipe ratio, or opening balance may be assumed without explicit Owner/CA sign-off here.']
    ],
    ['Decision ID', 'Domain', 'Decision / Confirmation Required', 'Sign-Off Authority', 'Status', 'Approved Value / Reference'],
    decisions
  );

  Logger.log('Generated RPT_Section17_OpenDecisions tab.');
}

/**
 * 7. Formal Phase H Owner Go-Live Sign-Off Recorder (GATE-08).
 */
function ksRecordOwnerGoLiveSignOff(backupFileId, caSignOffRef) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksRecordOwnerGoLiveSignOff');
  if (!backupFileId || !caSignOffRef) {
    throw new Error('Both backupFileId (from BackupRegister) and caSignOffRef are required before Go-Live sign-off (POL-018).');
  }

  const baseline = ksVerifyCleanLiveBaseline();
  if (!baseline.clean_transaction_baseline) {
    throw new Error(
      'GO-LIVE BLOCKED (POL-017): Workbook contains non-empty transaction tables (' +
      baseline.dirty_or_missing_tables.map(t => t.tab).join(', ') +
      '). Deploy to a clean 0-row production copy first.'
    );
  }

  if (baseline.configured_users_count < 1) {
    throw new Error('GO-LIVE BLOCKED: Populate at least 1 active user in the Users master tab before Go-Live.');
  }

  const auditId = ksLogAudit_('OWNER_GO_LIVE_APPROVED', 'WORKBOOK', 'PRODUCTION_RELEASE_V2', {
    actor_user_id: ctx.user_id,
    field_changed: 'release_status',
    old_value: 'PRE_RELEASE',
    new_value: 'LIVE_APPROVED',
    reason: 'BackupID=' + backupFileId + ' | CA_SignOff=' + caSignOffRef,
    approved_by_user_id: ctx.user_id
  });

  Logger.log('PHASE H GO-LIVE APPROVED! Audit ID: ' + auditId);
  return { success: true, status: 'LIVE_APPROVED', audit_id: auditId };
}