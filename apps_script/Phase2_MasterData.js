/**
 * KAWAD SWAD ERP - PHASE 2 GOOGLE SHEETS MASTER DATA
 * Version: 2.0.0
 *
 * INSTALL:
 * 1. Open the LIVE Kawad Swad Google Sheet.
 * 2. Extensions > Apps Script.
 * 3. Add a NEW file named Phase2_MasterData.gs.
 * 4. Paste this entire file and Save.
 * 5. Run ksP2InstallMasterData() once from the Apps Script editor.
 *
 * SAFETY:
 * - Verifies the target spreadsheet ID before any write.
 * - Makes a Drive backup before changing the workbook.
 * - Does not rename, delete, reorder, clear or rewrite existing business tabs,
 *   headers, IDs, formulas or transaction rows.
 * - Does not create the proposed placeholder tabs as active business tables.
 * - Creates only two Phase 2 governance tabs.
 * - Applies warning-only dropdown validation to selected existing columns.
 * - Master record creation is opt-in through ksP2CreateMasterRecord().
 * - AuthUsers/password hashes are deliberately excluded from generic writes.
 *
 * SOURCE BASELINE:
 * Uploaded workbook: Kawad_Swad_Sales_Management_Google_Sheets (21).xlsx
 * Reviewed master tabs: Products, Customers, Suppliers, RawMaterials,
 * Users, AuthUsers, Settings, IdAllocations and configuration placeholders.
 *
 * GOOGLE SHEETS IS THE AUTHORITATIVE BUSINESS RECORD.
 * MongoDB must remain optional cache/processing only.
 */

const KS_P2 = Object.freeze({
  VERSION: '2.0.0',
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME_PREFIX: 'Kawad_Swad_Sales_Management_Google_Sheets',
  RULES_TAB: 'KS_P2_MASTER_DATA_RULES',
  LOG_TAB: 'KS_P2_DEPLOYMENT_LOG',
  ALLOCATION_TAB: 'IdAllocations',
  MAX_SCAN_ROWS: 50000
});

/**
 * Approved, existing operational master tabs only.
 * Required headers are checked by name, never by column position.
 */
const KS_P2_TABLES = Object.freeze({
  Products: {
    idHeader: 'product_id',
    prefix: 'PRD',
    required: ['product_id', 'sku', 'product_name'],
    unique: ['product_id', 'sku']
  },
  Customers: {
    idHeader: 'customer_id',
    prefix: 'CUS',
    required: ['customer_id', 'customer_type'],
    unique: ['customer_id']
  },
  Suppliers: {
    idHeader: 'supplier_id',
    prefix: 'SUP',
    required: ['supplier_id', 'supplier_name'],
    unique: ['supplier_id']
  },
  RawMaterials: {
    idHeader: 'raw_material_id',
    prefix: null,
    required: ['raw_material_id', 'material_name', 'unit'],
    unique: ['raw_material_id']
  }
});

/**
 * Installer. Run once. Safe to run again: only its own two KS_P2 tabs are
 * refreshed; operational business tabs are never cleared or rewritten.
 */
function ksP2InstallMasterData() {
  const ss = SpreadsheetApp.openById(KS_P2.SPREADSHEET_ID);
  ksP2AssertWorkbook_(ss);

  const backup = DriveApp.getFileById(ss.getId()).makeCopy(
    'Kawad Swad ERP Phase 2 Pre-Deployment Backup ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMdd-HHmmss')
  );

  const report = ksP2BuildRules_();
  ksP2WriteOwnedTab_(ss, KS_P2.RULES_TAB, report.headers, report.rows);
  ksP2InstallWarningValidations_(ss);
  ksP2AppendDeploymentLog_(ss, 'PHASE_2_MASTER_DATA_INSTALLED',
    'Created/updated Phase 2 rule register; applied warning-only validations. ' +
    'No operational records, headers or IDs were rewritten. Backup: ' + backup.getUrl());

  SpreadsheetApp.flush();

  const summary = [
    'Phase 2 master-data foundation installed.',
    'Rules registered: ' + report.rows.length,
    'Operational business records changed: NO',
    'Existing business headers changed: NO',
    'Backup: ' + backup.getUrl()
  ].join('\n');

  Logger.log(summary);
  return {success: true, rules: report.rows.length, backupUrl: backup.getUrl(), message: summary};
}

function ksP2AssertWorkbook_(ss) {
  if (!ss) throw new Error('Target spreadsheet could not be opened.');
  if (ss.getId() !== KS_P2.SPREADSHEET_ID) {
    throw new Error('Safety stop: spreadsheet ID does not match Phase 2 target.');
  }
  if (ss.getName().indexOf(KS_P2.EXPECTED_NAME_PREFIX) !== 0) {
    throw new Error('Safety stop: spreadsheet name does not match Kawad Swad workbook.');
  }
}

/**
 * Creates a decision register, not 218 new business sheets.
 * Placeholder tabs remain inactive until their real schema and use are approved.
 */
function ksP2BuildRules_() {
  const headers = [
    'area', 'existing_tab', 'phase2_decision', 'purpose',
    'required_headers_checked', 'unique_fields', 'validation_rule',
    'implementation_status', 'safety_note'
  ];
  const rows = [
    ['Product Master', 'Products', 'KEEP_AND_CONTROL',
      'Existing product and pack SKU master.',
      'product_id; sku; product_name', 'product_id; sku',
      'ID and SKU duplicate checks; warning-only Yes/No validation where present.',
      'ACTIVE_EXISTING_TAB',
      'Preserve all 46 existing product rows and current header order.'],
    ['Customer Master', 'Customers', 'KEEP_AND_CONTROL',
      'Existing customer and retailer records.',
      'customer_id; customer_type', 'customer_id',
      'Customer ID duplicate check; no assumptions about mobile uniqueness.',
      'ACTIVE_EXISTING_TAB',
      'Preserve existing customer rows, including any test/legacy record.'],
    ['Supplier Master', 'Suppliers', 'KEEP_AND_CONTROL',
      'Supplier identity and payment terms.',
      'supplier_id; supplier_name', 'supplier_id',
      'Supplier ID duplicate check.',
      'ACTIVE_EXISTING_TAB',
      'Do not create supplier records or infer GST/payment terms.'],
    ['Raw Material Master', 'RawMaterials', 'KEEP_AND_CONTROL',
      'Raw material identity, unit, stock and rate metadata.',
      'raw_material_id; material_name; unit', 'raw_material_id',
      'Raw material ID duplicate check; preserve stock/rate columns.',
      'ACTIVE_EXISTING_TAB',
      'Current stock is not recalculated or overwritten by this installer.'],
    ['User Directory', 'Users', 'KEEP_RESTRICTED',
      'ERP user directory and role assignment.',
      'user_id; full_name; role', 'user_id',
      'Restricted; no generic create/update operation in this module.',
      'EXISTING_RESTRICTED_TAB',
      'Employee information is confidential. No employee data is exported.'],
    ['Authentication', 'AuthUsers', 'KEEP_HIGHLY_RESTRICTED',
      'Login identity and password hash records.',
      'auth_id; user_id; username; password_hash', 'auth_id; username',
      'No generic writes, no password display, no password changes.',
      'EXISTING_SECURITY_TAB',
      'Never expose password_hash or session security fields.'],
    ['Configuration', 'Settings', 'KEEP_AND_CONTROL',
      'Key/value configuration store.',
      'setting_key; setting_value; description', 'setting_key',
      'Values remain text/JSON-capable; do not coerce to numeric.',
      'EXISTING_CONFIG_TAB',
      'Existing settings are preserved. No default values are injected.'],
    ['ID Allocation', 'IdAllocations', 'USE_EXISTING_LEDGER',
      'Central reservation ledger for new master IDs.',
      'allocation_id; tab_name; allocated_id; nonce; created_at', 'allocated_id; nonce',
      'LockService + unique nonce + scan existing IDs and reservations.',
      'EXISTING_CONTROL_TAB',
      'No counter reset and no historical ID backfill.'],
    ['Product Variants', 'ProductVariants', 'REVIEW_NOT_ACTIVATED',
      'Proposed separate variant model.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Do not activate placeholder schema until product/SKU model is approved.',
      'PLACEHOLDER_ONLY',
      'Products currently contains variant and pack_weight_g. Avoid duplicate authority.'],
    ['Product SKU', 'Products_SKU', 'REVIEW_NOT_ACTIVATED',
      'Proposed separate SKU registry.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Do not activate placeholder schema.',
      'PLACEHOLDER_ONLY',
      'Products already has sku and pack_weight_g. Reconcile before any migration.'],
    ['Product Prices', 'ProductPrices', 'REVIEW_NOT_ACTIVATED',
      'Proposed effective-dated price records.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Do not activate placeholder schema or invent prices.',
      'PLACEHOLDER_ONLY',
      'Price model must be reconciled with current sales/backend and website pricing.'],
    ['Product Tax Rules', 'ProductTaxRules', 'REVIEW_NOT_ACTIVATED',
      'Proposed product tax classification.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Do not hardcode a tax rate.',
      'PLACEHOLDER_ONLY',
      'Tax classification requires verified product and invoice evidence.'],
    ['Units of Measurement', 'UnitsOfMeasurement', 'REVIEW_NOT_ACTIVATED',
      'Proposed central unit dictionary.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Do not replace units already stored in operational tabs.',
      'PLACEHOLDER_ONLY',
      'RawMaterials currently stores unit as text; migration mapping is required.'],
    ['Company Profile', 'CompanyProfile', 'REVIEW_NOT_ACTIVATED',
      'Proposed company identity/configuration record.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Placeholder only; no company values invented.',
      'PLACEHOLDER_ONLY',
      'Requires owner-confirmed legal and business information.'],
    ['Business Registrations', 'BusinessRegistrations', 'REVIEW_NOT_ACTIVATED',
      'Proposed registration and compliance details.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Placeholder only; no registration data invented.',
      'PLACEHOLDER_ONLY',
      'Sensitive legal identifiers must have restricted access.'],
    ['Factory Locations', 'FactoryLocations', 'REVIEW_NOT_ACTIVATED',
      'Proposed factory/location master.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Placeholder only; no location records invented.',
      'PLACEHOLDER_ONLY',
      'Requires verified operational location structure.'],
    ['Warehouses', 'Warehouses', 'REVIEW_NOT_ACTIVATED',
      'Proposed warehouse master.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Placeholder only; do not create stock locations implicitly.',
      'PLACEHOLDER_ONLY',
      'Must be reconciled with current stock ledgers before activation.'],
    ['Storage Locations', 'StorageLocations', 'REVIEW_NOT_ACTIVATED',
      'Proposed bin/rack/storage-location master.',
      'record_id; created_at; created_by; updated_at; updated_by; status; notes',
      '', 'Placeholder only.',
      'PLACEHOLDER_ONLY',
      'No warehouse hierarchy is assumed.']
  ];
  return {headers: headers, rows: rows};
}

/**
 * Only adds warning-mode validations to existing columns found by exact header.
 * Existing values are not changed. Missing tabs/headers are logged and skipped.
 */
function ksP2InstallWarningValidations_(ss) {
  const rules = [
    {tab: 'Products', header: 'active', values: ['Yes', 'No', 'true', 'false']},
    {tab: 'Products', header: 'retail_pack_only', values: ['Yes', 'No', 'true', 'false']},
    {tab: 'Customers', header: 'active', values: ['Yes', 'No', 'true', 'false']},
    {tab: 'Suppliers', header: 'active', values: ['Yes', 'No', 'true', 'false']},
    {tab: 'RawMaterials', header: 'active', values: ['Yes', 'No', 'true', 'false']}
  ];

  rules.forEach(function(rule) {
    const sh = ss.getSheetByName(rule.tab);
    if (!sh) {
      Logger.log('Validation skipped: missing tab ' + rule.tab);
      return;
    }
    const col = ksP2FindHeaderColumn_(sh, rule.header);
    if (!col) {
      Logger.log('Validation skipped: missing header ' + rule.tab + '.' + rule.header);
      return;
    }
    const maxRows = Math.max(sh.getMaxRows(), 1000);
    if (sh.getMaxRows() < maxRows) sh.insertRowsAfter(sh.getMaxRows(), maxRows - sh.getMaxRows());
    const validation = SpreadsheetApp.newDataValidation()
      .requireValueInList(rule.values, true)
      .setAllowInvalid(true)
      .setHelpText('Use Yes/No for new entries. Existing values are preserved.')
      .build();
    sh.getRange(2, col, maxRows - 1, 1).setDataValidation(validation);
  });
}

function ksP2FindHeaderColumn_(sh, headerName) {
  const lastCol = sh.getLastColumn();
  if (!lastCol) return 0;
  const headers = sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0];
  const index = headers.findIndex(function(v) {
    return String(v).trim().toLowerCase() === String(headerName).trim().toLowerCase();
  });
  return index < 0 ? 0 : index + 1;
}

/**
 * Allocate one new ID using the existing IdAllocations ledger.
 * Examples:
 *   ksP2AllocateId('Products')
 *   ksP2AllocateId('Customers')
 *   ksP2AllocateId('Suppliers')
 *   ksP2AllocateId('RawMaterials')
 *
 * Allocation reserves an ID but does not create a business record.
 * Never use this to backfill or replace historical IDs.
 */
function ksP2AllocateId(tableName) {
  const cfg = KS_P2_TABLES[tableName];
  if (!cfg || !cfg.prefix) throw new Error('Automatic ID allocation is not enabled for: ' + tableName + '. Supply an owner-approved ID.');

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.openById(KS_P2.SPREADSHEET_ID);
    ksP2AssertWorkbook_(ss);

    const target = ss.getSheetByName(tableName);
    const ledger = ss.getSheetByName(KS_P2.ALLOCATION_TAB);
    if (!target || !ledger) throw new Error('Required target or IdAllocations tab is missing.');

    const idCol = ksP2FindHeaderColumn_(target, cfg.idHeader);
    if (!idCol) throw new Error('Required ID header missing: ' + tableName + '.' + cfg.idHeader);

    const ledgerHeaders = ledger.getRange(1, 1, 1, ledger.getLastColumn()).getDisplayValues()[0];
    ['allocation_id', 'tab_name', 'allocated_id', 'nonce', 'created_at'].forEach(function(h) {
      if (ledgerHeaders.indexOf(h) < 0) throw new Error('IdAllocations missing header: ' + h);
    });

    const used = {};
    const targetLast = Math.min(target.getLastRow(), KS_P2.MAX_SCAN_ROWS);
    if (targetLast >= 2) {
      target.getRange(2, idCol, targetLast - 1, 1).getDisplayValues().forEach(function(r) {
        if (r[0]) used[String(r[0]).trim()] = true;
      });
    }

    const ledgerLast = Math.min(ledger.getLastRow(), KS_P2.MAX_SCAN_ROWS);
    const ledgerRows = ledgerLast >= 2
      ? ledger.getRange(2, 1, ledgerLast - 1, ledger.getLastColumn()).getValues()
      : [];
    const tabIndex = ledgerHeaders.indexOf('tab_name');
    const idIndex = ledgerHeaders.indexOf('allocated_id');
    const nonceIndex = ledgerHeaders.indexOf('nonce');
    ledgerRows.forEach(function(r) {
      if (r[tabIndex] === tableName && r[idIndex]) used[String(r[idIndex]).trim()] = true;
    });

    let max = 0;
    let width = 4;
    Object.keys(used).forEach(function(id) {
      const match = id.match(new RegExp('^' + cfg.prefix.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '-(\\d+)$'));
      if (match) {
        max = Math.max(max, Number(match[1]));
        width = Math.max(width, match[1].length);
      }
    });

    let candidate;
    do {
      max += 1;
      candidate = cfg.prefix + '-' + String(max).padStart(width, '0');
    } while (used[candidate]);

    const nonce = Utilities.getUuid();
    const allocationId = 'ALC-' + Utilities.getUuid();
    const row = new Array(ledgerHeaders.length).fill('');
    row[ledgerHeaders.indexOf('allocation_id')] = allocationId;
    row[tabIndex] = tableName;
    row[idIndex] = candidate;
    row[nonceIndex] = nonce;
    row[ledgerHeaders.indexOf('created_at')] = new Date();

    ledger.appendRow(row);
    SpreadsheetApp.flush();

    return {success: true, table: tableName, allocated_id: candidate, nonce: nonce};
  } finally {
    lock.releaseLock();
  }
}

/**
 * Creates a new record only in the four approved master tabs.
 * Supply an object whose keys exactly match existing header names.
 * ID is allocated automatically if omitted.
 *
 * Example:
 * ksP2CreateMasterRecord('Products', {
 *   sku: 'KS-EXAMPLE-200',
 *   product_name: 'Example Product',
 *   category: 'Papad',
 *   variant: 'Plain',
 *   pack_weight_g: 200,
 *   selling_unit: 'packet',
 *   active: 'Yes'
 * });
 *
 * This function never edits an existing row.
 */
function ksP2CreateMasterRecord(tableName, record) {
  const cfg = KS_P2_TABLES[tableName];
  if (!cfg) throw new Error('Master record creation is not enabled for: ' + tableName);
  if (!record || typeof record !== 'object' || Array.isArray(record)) {
    throw new Error('Record must be a plain object.');
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.openById(KS_P2.SPREADSHEET_ID);
    ksP2AssertWorkbook_(ss);
    const sh = ss.getSheetByName(tableName);
    if (!sh) throw new Error('Master tab not found: ' + tableName);

    const lastCol = sh.getLastColumn();
    const headers = sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0].map(function(h) {
      return String(h).trim();
    });
    const headerMap = {};
    headers.forEach(function(h, i) { if (h) headerMap[h] = i; });

    cfg.required.forEach(function(h) {
      if (headerMap[h] === undefined) throw new Error('Required header missing: ' + tableName + '.' + h);
    });

    Object.keys(record).forEach(function(k) {
      if (headerMap[k] === undefined) throw new Error('Unknown field, refusing to write: ' + k);
    });

    const clean = {};
    Object.keys(record).forEach(function(k) {
      clean[k] = record[k];
    });

    if (!clean[cfg.idHeader]) {
      // Reserve under the same script lock without recursively acquiring it.
      clean[cfg.idHeader] = ksP2AllocateIdUnderLock_(ss, tableName, cfg);
    }

    cfg.required.forEach(function(h) {
      if (clean[h] === undefined || clean[h] === null || String(clean[h]).trim() === '') {
        throw new Error('Required value missing: ' + h);
      }
    });

    const lastRow = Math.min(sh.getLastRow(), KS_P2.MAX_SCAN_ROWS);
    const rows = lastRow >= 2 ? sh.getRange(2, 1, lastRow - 1, lastCol).getValues() : [];
    cfg.unique.forEach(function(uniqueHeader) {
      const idx = headerMap[uniqueHeader];
      const incoming = String(clean[uniqueHeader]).trim().toLowerCase();
      if (rows.some(function(r) { return String(r[idx] || '').trim().toLowerCase() === incoming; })) {
        throw new Error('Duplicate ' + uniqueHeader + ' refused: ' + clean[uniqueHeader]);
      }
    });

    const output = new Array(headers.length).fill('');
    Object.keys(clean).forEach(function(k) { output[headerMap[k]] = clean[k]; });

    sh.appendRow(output);
    SpreadsheetApp.flush();

    return {success: true, table: tableName, id: clean[cfg.idHeader], row: sh.getLastRow()};
  } finally {
    lock.releaseLock();
  }
}

/** Internal allocator used while ksP2CreateMasterRecord already holds the lock. */
function ksP2AllocateIdUnderLock_(ss, tableName, cfg) {
  if (!cfg.prefix) throw new Error('Automatic ID allocation is not enabled for ' + tableName + '. Supply an owner-approved ID.');
  const target = ss.getSheetByName(tableName);
  const ledger = ss.getSheetByName(KS_P2.ALLOCATION_TAB);
  if (!target || !ledger) throw new Error('Required target or IdAllocations tab is missing.');

  const idCol = ksP2FindHeaderColumn_(target, cfg.idHeader);
  const ledgerHeaders = ledger.getRange(1, 1, 1, ledger.getLastColumn()).getDisplayValues()[0];
  const requiredLedger = ['allocation_id', 'tab_name', 'allocated_id', 'nonce', 'created_at'];
  requiredLedger.forEach(function(h) {
    if (ledgerHeaders.indexOf(h) < 0) throw new Error('IdAllocations missing header: ' + h);
  });

  const used = {};
  const targetLast = Math.min(target.getLastRow(), KS_P2.MAX_SCAN_ROWS);
  if (targetLast >= 2) {
    target.getRange(2, idCol, targetLast - 1, 1).getDisplayValues().forEach(function(r) {
      if (r[0]) used[String(r[0]).trim()] = true;
    });
  }

  const ledgerLast = Math.min(ledger.getLastRow(), KS_P2.MAX_SCAN_ROWS);
  const ledgerRows = ledgerLast >= 2
    ? ledger.getRange(2, 1, ledgerLast - 1, ledger.getLastColumn()).getValues()
    : [];
  const ti = ledgerHeaders.indexOf('tab_name');
  const ii = ledgerHeaders.indexOf('allocated_id');
  ledgerRows.forEach(function(r) {
    if (r[ti] === tableName && r[ii]) used[String(r[ii]).trim()] = true;
  });

  let max = 0;
  let width = 4;
  Object.keys(used).forEach(function(id) {
    const m = id.match(new RegExp('^' + cfg.prefix + '-(\\d+)$'));
    if (m) {
      max = Math.max(max, Number(m[1]));
      width = Math.max(width, m[1].length);
    }
  });
  let candidate;
  do {
    max += 1;
    candidate = cfg.prefix + '-' + String(max).padStart(width, '0');
  } while (used[candidate]);

  const row = new Array(ledgerHeaders.length).fill('');
  row[ledgerHeaders.indexOf('allocation_id')] = 'ALC-' + Utilities.getUuid();
  row[ti] = tableName;
  row[ii] = candidate;
  row[ledgerHeaders.indexOf('nonce')] = Utilities.getUuid();
  row[ledgerHeaders.indexOf('created_at')] = new Date();
  ledger.appendRow(row);
  return candidate;
}

function ksP2WriteOwnedTab_(ss, tabName, headers, rows) {
  let sh = ss.getSheetByName(tabName);
  if (!sh) sh = ss.insertSheet(tabName);

  // Only the two Phase 2-owned tabs are cleared/refreshed.
  sh.clearContents();
  if (headers.length) {
    sh.getRange(1, 1, 1, headers.length).setValues([headers]);
    sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  if (rows.length) {
    sh.getRange(2, 1, rows.length, headers.length).setValues(rows);
  }
  sh.autoResizeColumns(1, headers.length);
}

function ksP2AppendDeploymentLog_(ss, action, details) {
  const headers = ['timestamp', 'version', 'action', 'details', 'spreadsheet_id'];
  let sh = ss.getSheetByName(KS_P2.LOG_TAB);
  if (!sh) {
    sh = ss.insertSheet(KS_P2.LOG_TAB);
    sh.getRange(1, 1, 1, headers.length).setValues([headers]);
    sh.setFrozenRows(1);
  }
  const existing = sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), headers.length))
    .getDisplayValues()[0];
  headers.forEach(function(h) {
    if (existing.indexOf(h) < 0) throw new Error('Phase 2 deployment log header conflict: ' + h);
  });
  sh.appendRow([new Date(), KS_P2.VERSION, action, details, ss.getId()]);
}

/**
 * Read-only preview of current master tabs. Logs only counts and header names,
 * never cell values, employee details, credentials, phone numbers or GSTINs.
 */
function ksP2PreviewMasterData() {
  const ss = SpreadsheetApp.openById(KS_P2.SPREADSHEET_ID);
  ksP2AssertWorkbook_(ss);
  const result = {};
  Object.keys(KS_P2_TABLES).forEach(function(tabName) {
    const sh = ss.getSheetByName(tabName);
    if (!sh) {
      result[tabName] = {exists: false};
      return;
    }
    const headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getDisplayValues()[0];
    result[tabName] = {
      exists: true,
      data_rows: Math.max(0, sh.getLastRow() - 1),
      headers: headers,
      required_headers_present: KS_P2_TABLES[tabName].required.every(function(h) {
        return headers.indexOf(h) >= 0;
      })
    };
  });
  Logger.log(JSON.stringify(result, null, 2));
  return result;
}
