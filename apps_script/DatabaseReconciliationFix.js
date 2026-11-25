/**
 * KAWAD SWAD ERP - CONTROLLED DATABASE SCHEMA RECONCILIATION, HEADER CLEANUP & BASELINE FINALIZER
 * Enforces Blueprint v2.0 & Constitution v1.2 (POL-008, POL-017, POL-018).
 *
 * Capabilities:
 *  1. ksPreviewDatabaseReconciliation()      -> Dry-run preview of dictionary headers & legacy tabs.
 *  2. ksRunDatabaseReconciliationNow()       -> Hydrates 218 canonical tables, adds Journal debit/credit,
 *                                               and tags/hides 30 legacy tabs as LEGACY_READONLY_*.
 *  3. ksRunCleanHeadersAndBaselineNow()      -> Purges Phase G test rows, deletes obsolete empty Row-1
 *                                               headers, updates START_HERE banner, and logs to AuditLog.
 *  4. ksInspectCleanReadiness()              -> Read-only check verifying 0 transaction rows & clean V2.0 state.
 */

const KS_NONCANONICAL_LEGACY_TABS = Object.freeze([
  'AccountingPeriods',
  'ComplaintsRecalls',
  'CustomerReturnItems',
  'CustomerReturns',
  'DailyClosing',
  'FreelancerMilestones',
  'FreelancerProjects',
  'JournalHeaders',
  'JournalLines',
  'LabourAttendance',
  'LabourMaster',
  'LabourWageRecords',
  'LabourWorkEntries',
  'LotMovements',
  'Payments',
  'ProductionDispatches',
  'ProductionStockLedger',
  'QualityChecks',
  'RawMaterialLedger',
  'RawMaterialLedger_ID_Repair_Pre',
  'SalaryReceipts',
  'SaleItems',
  'Sales',
  'SalesmanStockLedger',
  'ShopVisits',
  'VanLoadingPasses',
  'WorkerAttendance',
  'Workers',
  'WorkforceAuditLogs',
  'WorkforcePayments'
]);

const KS_CORE_TRANSACTION_TABS_TO_VERIFY_EMPTY = Object.freeze([
  'InventoryLots',
  'InventoryMovements',
  'PurchaseOrders',
  'PurchaseOrderItems',
  'GoodsReceipts',
  'GoodsReceiptItems',
  'SupplierBills',
  'SupplierPayments',
  'ProductionOrders',
  'ProductionBatches',
  'MillingBatches',
  'MaterialConsumption',
  'ProductionOutputs',
  'ProcessLosses',
  'InProcessQualityChecks',
  'FinishedGoodsQualityChecks',
  'PackagingBatches',
  'PackagingOutputs',
  'SalesOrders',
  'SalesOrderItems',
  'SalesInvoices',
  'SalesInvoiceItems',
  'CustomerPayments',
  'CustomerPaymentAllocations',
  'JournalEntries',
  'JournalEntryLines',
  'ProductionWorkerEntries',
  'SalaryPayments',
  'EmployeeAdvances'
]);

/**
 * 1. Dry-Run Preview (Read-Only)
 */
function ksPreviewDatabaseReconciliation() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksPreviewDatabaseReconciliation');
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dictMap = ksLoadFullFieldDictionaryMap_(ss);

  let tablesToHydrate = 0;
  let totalColumnsToAppend = 0;
  const previewDetails = [];

  Object.keys(dictMap).forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) return;
    const existingHeaders = sh.getLastColumn() > 0
      ? sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(h => String(h).trim())
      : [];
    const existingSet = new Set(existingHeaders.filter(Boolean));
    const missingCols = dictMap[tabName].filter(col => !existingSet.has(col));

    if (missingCols.length > 0) {
      tablesToHydrate++;
      totalColumnsToAppend += missingCols.length;
      previewDetails.push({
        tab: tabName,
        existing_cols: existingHeaders.length,
        missing_cols_count: missingCols.length,
        sample_missing: missingCols.slice(0, 6)
      });
    }
  });

  const legacyPresent = KS_NONCANONICAL_LEGACY_TABS.filter(t => !!ss.getSheetByName(t));

  Logger.log('=== DATABASE RECONCILIATION DRY-RUN PREVIEW ===');
  Logger.log('Canonical tables in dictionary: ' + Object.keys(dictMap).length);
  Logger.log('Tables needing dictionary header hydration: ' + tablesToHydrate + ' (total columns to append: ' + totalColumnsToAppend + ')');
  Logger.log('Noncanonical legacy tabs present to tag LEGACY_READONLY_: ' + legacyPresent.length);
  Logger.log(JSON.stringify(previewDetails.slice(0, 25), null, 2));

  return {
    checked_by: ctx.user_id,
    canonical_tables_found: Object.keys(dictMap).length,
    tables_to_hydrate: tablesToHydrate,
    total_columns_to_append: totalColumnsToAppend,
    legacy_tabs_to_tag: legacyPresent.length
  };
}

/**
 * 2. Execute Controlled Database Reconciliation (Hydrate Dictionary + Double-Entry + Quarantine Legacy Tabs)
 */
function ksExecuteDatabaseReconciliation(confirmationPhrase) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksExecuteDatabaseReconciliation');
  if (confirmationPhrase !== 'RECONCILE_DISPOSABLE_OR_STAGING_DB') {
    throw new Error('Safety Lock (POL-018): Pass exact phrase "RECONCILE_DISPOSABLE_OR_STAGING_DB" to run schema reconciliation.');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dictMap = ksLoadFullFieldDictionaryMap_(ss);

  let hydratedTablesCount = 0;
  let appendedColsCount = 0;

  // Step A: Hydrate all 218 canonical tables from DBV5_FIELD_DICTIONARY_3074
  Object.keys(dictMap).forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh) return;

    const lastCol = sh.getLastColumn();
    const existingHeaders = lastCol > 0
      ? sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim())
      : [];
    const existingSet = new Set(existingHeaders.filter(Boolean));
    const missingCols = dictMap[tabName].filter(col => !existingSet.has(col));

    if (missingCols.length > 0) {
      const startCol = existingHeaders.length + 1;
      sh.getRange(1, startCol, 1, missingCols.length).setValues([missingCols]);
      sh.getRange(1, startCol, 1, missingCols.length).setFontWeight('bold');
      hydratedTablesCount++;
      appendedColsCount += missingCols.length;
    }
  });

  // Step B: Enforce POL-008 Double-Entry Split Columns on Canonical Journal Tables
  const jvHeadAdded = ksEnsureColumnsExist_(ss, 'JournalEntries', ['total_debit', 'total_credit', 'financial_period_id', 'posting_status']);
  const jvLineAdded = ksEnsureColumnsExist_(ss, 'JournalEntryLines', ['debit_amount', 'credit_amount', 'account_code', 'cost_centre_id']);

  // Step C: Quarantine 30 Noncanonical Legacy Operational Tabs as LEGACY_READONLY_*
  const taggedLegacyTabs = [];
  KS_NONCANONICAL_LEGACY_TABS.forEach(legacyName => {
    const sh = ss.getSheetByName(legacyName);
    if (!sh) return;
    const archivedName = 'LEGACY_READONLY_' + legacyName;
    if (!ss.getSheetByName(archivedName)) {
      sh.setName(archivedName);
      sh.hideSheet();
      taggedLegacyTabs.push(legacyName + ' -> ' + archivedName);
    }
  });

  SpreadsheetApp.flush();

  ksLogAudit_('DATABASE_SCHEMA_RECONCILED', 'WORKBOOK', ss.getId(), {
    actor_user_id: ctx.user_id,
    field_changed: 'canonical_headers_and_legacy_tabs',
    old_value: 'Placeholder headers + overlapping legacy tabs',
    new_value: 'Hydrated ' + hydratedTablesCount + ' tables (+' + appendedColsCount + ' cols), Journal debit/credit split enforced, Tagged ' + taggedLegacyTabs.length + ' legacy tabs',
    reason: 'Executed schema reconciliation per POL-008 & POL-018',
    approved_by_user_id: ctx.user_id
  });

  const summary = {
    success: true,
    hydrated_tables: hydratedTablesCount,
    appended_columns: appendedColsCount,
    journal_entries_cols_added: jvHeadAdded,
    journal_lines_cols_added: jvLineAdded,
    tagged_legacy_tabs_count: taggedLegacyTabs.length,
    tagged_legacy_tabs: taggedLegacyTabs
  };

  Logger.log('=== DATABASE RECONCILIATION COMPLETE ===');
  Logger.log(JSON.stringify(summary, null, 2));
  return summary;
}

function ksRunDatabaseReconciliationNow() {
  return ksExecuteDatabaseReconciliation('RECONCILE_DISPOSABLE_OR_STAGING_DB');
}

/**
 * 3. Safe Old-Header Cleaner & V2.0 Baseline Finalizer (POL-017 & POL-018):
 * - Purges leftover Phase G test rows (Row 2+) across transactional tables.
 * - Deletes obsolete non-dictionary columns from Row 1 ONLY if those columns have 0 data rows
 *   and are not protected system/audit/accounting columns.
 * - Updates START_HERE title banner to reflect V2.0 Clean Data-Entry Readiness.
 */
function ksFinalizeCleanHeadersAndBaseline(confirmationPhrase) {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksFinalizeCleanHeadersAndBaseline');
  if (confirmationPhrase !== 'FINALIZE_CLEAN_V2_SCHEMA_AND_RESET') {
    throw new Error('Safety Lock (POL-018): Pass exact phrase "FINALIZE_CLEAN_V2_SCHEMA_AND_RESET".');
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dictMap = ksLoadFullFieldDictionaryMap_(ss);

  // Step 1: Purge leftover test rows (Row 2+) so transactional tables start at clean 0-row baseline (POL-017)
  if (typeof ksPurgeTestRowsForCleanCutover === 'function') {
    ksPurgeTestRowsForCleanCutover('RESET_FOR_CLEAN_PRODUCTION_BASELINE');
  } else {
    KS_CORE_TRANSACTION_TABS_TO_VERIFY_EMPTY.forEach(tabName => {
      const sh = ss.getSheetByName(tabName);
      if (sh && sh.getLastRow() > 1) {
        sh.deleteRows(2, sh.getLastRow() - 1);
      }
    });
  }

  // Protected columns never stripped even if not explicitly listed in DBV5_FIELD_DICTIONARY_3074
  const protectedCols = new Set([
    'record_id', 'created_at', 'created_by', 'updated_at', 'updated_by', 'status', 'notes',
    'total_debit', 'total_credit', 'financial_period_id', 'posting_status',
    'debit_amount', 'credit_amount', 'account_code', 'cost_centre_id',
    'nonce', 'idempotency_key', 'correlation_id'
  ]);

  let cleanedTables = 0;
  let removedOldColsTotal = 0;
  const headerCleanupReport = [];

  // Step 2: Strip obsolete non-dictionary Row-1 headers that have 0 data rows
  Object.keys(dictMap).forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (!sh || sh.getLastColumn() === 0) return;

    const allowedSet = new Set(dictMap[tabName]);
    const lastCol = sh.getLastColumn();
    const lastRow = sh.getLastRow();
    const currentHeaders = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim());

    const removedInTab = [];
    for (let c = currentHeaders.length; c >= 1; c--) {
      const hName = currentHeaders[c - 1];
      if (!hName) continue;
      if (!allowedSet.has(hName) && !protectedCols.has(hName)) {
        let hasData = false;
        if (lastRow > 1) {
          const colVals = sh.getRange(2, c, lastRow - 1, 1).getValues();
          hasData = colVals.some(r => String(r[0] || '').trim() !== '');
        }
        if (!hasData) {
          sh.deleteColumn(c);
          removedInTab.push(hName);
          removedOldColsTotal++;
        }
      }
    }

    if (removedInTab.length > 0) {
      cleanedTables++;
      headerCleanupReport.push({ tab: tabName, removed_old_headers: removedInTab });
    }
  });

  // Step 3: Update START_HERE banner if still showing DEVELOPMENT TEMPLATE
  const startHere = ss.getSheetByName('START_HERE');
  if (startHere) {
    const banner = String(startHere.getRange('A1').getValue() || '');
    if (banner.indexOf('DEVELOPMENT TEMPLATE') !== -1) {
      startHere.getRange('A1').setValue('KAWAD SWAD ERP SYSTEM (V2.0) — CLEAN SCHEMA & DATA ENTRY BASELINE');
    }
  }

  SpreadsheetApp.flush();

  ksLogAudit_('OLD_HEADERS_CLEARED_FOR_V2_DATA_ENTRY', 'WORKBOOK', ss.getId(), {
    actor_user_id: ctx.user_id,
    field_changed: 'obsolete_row1_headers_and_test_rows',
    old_value: removedOldColsTotal + ' obsolete headers across ' + cleanedTables + ' tables',
    new_value: 'CLEAN_V2_DICTIONARY_SCHEMA_READY',
    reason: 'Cleared obsolete headers and purged test rows for clean V2.0 data entry (POL-017, POL-018)',
    approved_by_user_id: ctx.user_id
  });

  const result = {
    success: true,
    tables_cleaned: cleanedTables,
    obsolete_headers_removed: removedOldColsTotal,
    details: headerCleanupReport
  };

  Logger.log('=== CLEAN V2.0 SCHEMA & BASELINE READY FOR DATA ENTRY ===');
  Logger.log(JSON.stringify(result, null, 2));
  return result;
}

function ksRunCleanHeadersAndBaselineNow() {
  return ksFinalizeCleanHeadersAndBaseline('FINALIZE_CLEAN_V2_SCHEMA_AND_RESET');
}

/**
 * 4. Read-Only Readiness Inspection (Confirms 0 Transaction Rows & Clean V2.0 Schema)
 */
function ksInspectCleanReadiness() {
  const ctx = ksRequireRole_([KS_ROLES.OWNER_ADMIN], 'ksInspectCleanReadiness');
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const nonEmptyTxTabs = [];

  KS_CORE_TRANSACTION_TABS_TO_VERIFY_EMPTY.forEach(tabName => {
    const sh = ss.getSheetByName(tabName);
    if (sh && sh.getLastRow() > 1) {
      nonEmptyTxTabs.push({ tab: tabName, data_rows: sh.getLastRow() - 1 });
    }
  });

  const report = {
    checked_by: ctx.user_id,
    total_sheets: ss.getSheets().length,
    clean_transaction_baseline: nonEmptyTxTabs.length === 0,
    remaining_populated_tx_tabs: nonEmptyTxTabs
  };

  Logger.log('=== V2.0 CLEAN DATA-ENTRY READINESS CHECK ===');
  Logger.log(JSON.stringify(report, null, 2));
  return report;
}

/**
 * Loads all 218 canonical table -> ordered field_name arrays from DBV5_FIELD_DICTIONARY_3074.
 * Dynamically inspects Row 1 headers so it never misreads the table name column.
 */
function ksLoadFullFieldDictionaryMap_(ss) {
  const dictSheet = ss.getSheetByName('DBV5_FIELD_DICTIONARY_3074');
  if (!dictSheet || dictSheet.getLastRow() < 2) {
    throw new Error('DBV5_FIELD_DICTIONARY_3074 tab is missing or empty.');
  }

  const values = dictSheet.getDataRange().getValues();
  const rawHeaders = values[0].map(h => String(h).trim());
  const lowerHeaders = rawHeaders.map(h => h.toLowerCase());

  const tableCandidates = ['canonical_table_name', 'canonical_table', 'table_name', 'sheet_name', 'tab_name', 'table'];
  const fieldCandidates = ['field_name', 'canonical_field_name', 'column_name', 'header_name', 'field'];

  let tableCol = -1;
  for (let i = 0; i < tableCandidates.length; i++) {
    const idx = lowerHeaders.indexOf(tableCandidates[i]);
    if (idx !== -1) { tableCol = idx; break; }
  }

  let fieldCol = -1;
  for (let i = 0; i < fieldCandidates.length; i++) {
    const idx = lowerHeaders.indexOf(fieldCandidates[i]);
    if (idx !== -1) { fieldCol = idx; break; }
  }

  if (tableCol === -1 || fieldCol === -1) {
    throw new Error(
      'Could not locate table/field columns in DBV5_FIELD_DICTIONARY_3074. Found headers: ' +
      JSON.stringify(rawHeaders)
    );
  }

  const map = {};
  for (let r = 1; r < values.length; r++) {
    const tName = String(values[r][tableCol] || '').trim();
    const fName = String(values[r][fieldCol] || '').trim();
    if (!tName || !fName) continue;
    if (!map[tName]) map[tName] = [];
    if (!map[tName].includes(fName)) {
      map[tName].push(fName);
    }
  }
  return map;
}

/**
 * Appends required columns to a canonical tab if they do not already exist.
 */
function ksEnsureColumnsExist_(ss, tabName, requiredCols) {
  const sh = ss.getSheetByName(tabName);
  if (!sh) return [];
  const lastCol = sh.getLastColumn();
  const existing = lastCol > 0
    ? sh.getRange(1, 1, 1, lastCol).getValues()[0].map(h => String(h).trim())
    : [];
  const existingSet = new Set(existing.filter(Boolean));
  const toAdd = requiredCols.filter(c => !existingSet.has(c));

  if (toAdd.length > 0) {
    const startCol = existing.length + 1;
    sh.getRange(1, startCol, 1, toAdd.length).setValues([toAdd]);
    sh.getRange(1, startCol, 1, toAdd.length).setFontWeight('bold');
  }
  return toAdd;
}