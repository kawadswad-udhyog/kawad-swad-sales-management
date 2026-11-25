/**
 * KAWAD SWAD ERP - PHASE 3 INTEGRATED MASTER DATA
 * Version: 1.0.0
 *
 * Google Sheets remains the authoritative business record.
 *
 * Workstreams:
 *   1A - Controlled ID reservation (PRD, CUS, SUP)
 *   1B - Controlled Products and RawMaterials entry
 *   1C - Controlled Customers and Suppliers entry
 *   1D - Restricted Users profile updates (AuthUsers is never accessed)
 *
 * SAFETY:
 * - Never accesses AuthUsers.
 * - Users handler reads only user_id values and the selected safe profile field.
 * - Never reads/writes Users bank_details, document_references, role, active,
 *   username, salary fields, authentication data, or other restricted fields.
 * - Does not rename/delete/reorder tabs or alter existing headers.
 * - Does not edit existing business records, except a selected safe Users profile cell.
 * - New master records are appended only after validation.
 * - RawMaterials ID is owner-supplied pending resolution of the RWM prefix conflict.
 * - ScriptLock coordinates executions within this Apps Script project only.
 */

const KS_P3 = Object.freeze({
  VERSION: '1.0.0',
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  EXPECTED_NAME: 'Kawad_Swad_Sales_Management_Google_Sheets',
  ALLOCATION_TAB: 'IdAllocations',
  AUDIT_TAB: 'KS_P3_MASTER_DATA_AUDIT',
  EVENT_TAB: 'KS_P3_MASTER_DATA_EVENTS',
  ALLOCATION_HEADERS: ['allocation_id', 'tab_name', 'allocated_id', 'nonce', 'created_at'],
  TABLES: {
    Products: {
      idHeader: 'product_id', prefix: 'PRD',
      required: ['product_id', 'sku', 'product_name', 'category', 'variant',
                 'pack_weight_g', 'selling_unit', 'retail_pack_only', 'active', 'notes'],
      unique: ['product_id', 'sku']
    },
    Customers: {
      idHeader: 'customer_id', prefix: 'CUS',
      required: ['customer_id', 'customer_type', 'shop_name', 'shopkeeper_name',
                 'mobile', 'alternate_mobile', 'address', 'locality_area', 'city',
                 'map_location', 'active', 'created_at', 'notes', 'gstin'],
      unique: ['customer_id']
    },
    Suppliers: {
      idHeader: 'supplier_id', prefix: 'SUP',
      required: ['supplier_id', 'supplier_name', 'contact_person', 'mobile', 'email',
                 'address', 'city', 'gstin', 'payment_terms_days', 'opening_balance',
                 'active', 'notes', 'created_at', 'created_by'],
      unique: ['supplier_id']
    },
    RawMaterials: {
      idHeader: 'raw_material_id', prefix: null,
      required: ['raw_material_id', 'material_name', 'unit', 'opening_stock',
                 'current_stock', 'minimum_stock', 'active', 'notes',
                 'rate_per_unit', 'rate_status', 'category', 'created_at', 'created_by'],
      unique: ['raw_material_id']
    }
  },
  USER_SAFE_FIELDS: {
    full_name: 'Full name',
    mobile: 'Mobile',
    email: 'Email',
    designation: 'Designation',
    department: 'Department',
    employment_type: 'Employment type'
  }
});

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Kawad Swad | Phase 3')
    .addItem('1. Run Master Data Safety Audit', 'KS_P3_RUN_MASTER_AUDIT')
    .addSeparator()
    .addItem('1A. Reserve Product ID', 'KS_P3_RESERVE_PRODUCT_ID')
    .addItem('1A. Reserve Customer ID', 'KS_P3_RESERVE_CUSTOMER_ID')
    .addItem('1A. Reserve Supplier ID', 'KS_P3_RESERVE_SUPPLIER_ID')
    .addSeparator()
    .addItem('1B. Add Product', 'KS_P3_ADD_PRODUCT')
    .addItem('1B. Add Raw Material', 'KS_P3_ADD_RAW_MATERIAL')
    .addItem('1C. Add Customer', 'KS_P3_ADD_CUSTOMER')
    .addItem('1C. Add Supplier', 'KS_P3_ADD_SUPPLIER')
    .addSeparator()
    .addItem('1D. Update Safe User Profile Field', 'KS_P3_UPDATE_USER_PROFILE')
    .addToUi();
}

/* --------------------------- WORKBOOK GUARDS --------------------------- */

function ksP3GetWorkbook_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss || ss.getId() !== KS_P3.SPREADSHEET_ID) {
    throw new Error('SAFETY STOP: Workbook ID does not match the approved Kawad Swad workbook.');
  }
  if (ss.getName() !== KS_P3.EXPECTED_NAME) {
    throw new Error('SAFETY STOP: Workbook name does not exactly match the approved workbook.');
  }
  return ss;
}

function ksP3GetSheet_(ss, name) {
  const sh = ss.getSheetByName(name);
  if (!sh) throw new Error('Required sheet is missing: ' + name + '. No replacement sheet was created.');
  return sh;
}

function ksP3HeaderMap_(sh) {
  const lastCol = sh.getLastColumn();
  if (lastCol < 1) throw new Error(sh.getName() + ' has no header row.');
  const headers = sh.getRange(1, 1, 1, lastCol).getDisplayValues()[0].map(v => String(v).trim());
  const map = {};
  headers.forEach((h, i) => {
    if (!h) throw new Error(sh.getName() + ' has a blank header at column ' + (i + 1) + '.');
    if (map[h] !== undefined) throw new Error(sh.getName() + ' has duplicate header: ' + h);
    map[h] = i + 1;
  });
  return map;
}

function ksP3RequireHeaders_(sh, required) {
  const map = ksP3HeaderMap_(sh);
  const missing = required.filter(h => !map[h]);
  if (missing.length) {
    throw new Error('SAFETY STOP: ' + sh.getName() + ' is missing required live header(s): ' + missing.join(', '));
  }
  return map;
}

function ksP3Prompt_(ui, title, message, required) {
  const res = ui.prompt(title, message, ui.ButtonSet.OK_CANCEL);
  if (res.getSelectedButton() !== ui.Button.OK) throw new Error('Cancelled by user. No record created.');
  const value = String(res.getResponseText() || '').trim();
  if (required && !value) throw new Error('Required value was blank. No record created.');
  return value;
}

function ksP3PromptYesNo_(ui, title, message, defaultYes) {
  const label = defaultYes ? 'Y' : 'N';
  const value = ksP3Prompt_(ui, title, message + ' Enter Y or N. Default: ' + label, false).toUpperCase();
  if (!value) return defaultYes;
  if (value === 'Y' || value === 'YES') return true;
  if (value === 'N' || value === 'NO') return false;
  throw new Error('Enter Y or N. No record created.');
}

function ksP3Number_(value, field, required) {
  if (value === '' && !required) return '';
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) throw new Error(field + ' must be a valid non-negative number.');
  return n;
}

function ksP3Now_() {
  return new Date();
}

function ksP3Actor_() {
  // Email may be unavailable in some Google Workspace/personal-account contexts.
  return Session.getActiveUser().getEmail() || 'UNAVAILABLE';
}

/* --------------------------- AUDIT LOG --------------------------- */

function ksP3AuditLog_(ss, action, entity, entityId, outcome, detail) {
  let sh = ss.getSheetByName(KS_P3.EVENT_TAB);
  const headers = ['event_id', 'event_at', 'actor', 'action', 'entity', 'entity_id', 'outcome', 'detail'];
  if (!sh) {
    sh = ss.insertSheet(KS_P3.EVENT_TAB);
    sh.getRange(1, 1, 1, headers.length).setValues([headers]);
    sh.setFrozenRows(1);
  } else {
    const actual = ksP3HeaderMap_(sh);
    headers.forEach(h => { if (!actual[h]) throw new Error('Audit tab has unexpected structure. Missing: ' + h); });
  }
  sh.appendRow([
    'EVT-' + Utilities.getUuid(),
    ksP3Now_(),
    ksP3Actor_(),
    action,
    entity,
    entityId || '',
    outcome,
    detail || ''
  ]);
}

function KS_P3_RUN_MASTER_AUDIT() {
  const ss = ksP3GetWorkbook_();
  const targets = ['IdAllocations', 'Products', 'RawMaterials', 'Customers', 'Suppliers'];
  const rows = [];
  targets.forEach(name => {
    const sh = ksP3GetSheet_(ss, name);
    const map = ksP3HeaderMap_(sh);
    const required = name === 'IdAllocations'
      ? KS_P3.ALLOCATION_HEADERS
      : KS_P3.TABLES[name].required;
    const missing = required.filter(h => !map[h]);
    rows.push({
      tab: name,
      exists: true,
      physicalColumns: sh.getLastColumn(),
      headerCount: Object.keys(map).length,
      missingRequiredHeaders: missing,
      dataRows: Math.max(0, sh.getLastRow() - 1),
      result: missing.length ? 'STOP_REQUIRED_HEADER_MISSING' : 'STRUCTURE_OK'
    });
  });

  // Users: header-only check. Do not read employee rows.
  const users = ksP3GetSheet_(ss, 'Users');
  const userMap = ksP3HeaderMap_(users);
  const userRequired = ['user_id', 'full_name', 'mobile', 'email', 'designation', 'department'];
  const userMissing = userRequired.filter(h => !userMap[h]);
  rows.push({
    tab: 'Users',
    exists: true,
    physicalColumns: users.getLastColumn(),
    headerCount: Object.keys(userMap).length,
    missingRequiredHeaders: userMissing,
    dataRows: 'NOT_SCANNED',
    result: userMissing.length ? 'STOP_REQUIRED_HEADER_MISSING' : 'HEADER_ONLY_OK'
  });

  const reportHeaders = ['tab_name', 'exists', 'physical_columns', 'header_count',
                         'missing_required_headers', 'data_rows', 'result', 'checked_at'];
  let report = ss.getSheetByName(KS_P3.AUDIT_TAB);
  if (!report) report = ss.insertSheet(KS_P3.AUDIT_TAB);
  // This is a dedicated report tab. It is not a business table.
  report.clearContents();
  report.getRange(1, 1, 1, reportHeaders.length).setValues([reportHeaders]);
  const values = rows.map(r => [
    r.tab, r.exists, r.physicalColumns, r.headerCount,
    r.missingRequiredHeaders.join(', '), r.dataRows, r.result, ksP3Now_()
  ]);
  report.getRange(2, 1, values.length, reportHeaders.length).setValues(values);
  report.setFrozenRows(1);
  report.autoResizeColumns(1, reportHeaders.length);

  const allOk = rows.every(r => r.result === 'STRUCTURE_OK' || r.result === 'HEADER_ONLY_OK');
  console.log('KS_P3_MASTER_AUDIT_RESULT ' + JSON.stringify({
    success: allOk,
    status: allOk ? 'MASTER_DATA_STRUCTURE_AUDIT_PASSED' : 'MASTER_DATA_STRUCTURE_REVIEW_REQUIRED',
    results: rows,
    usersDataRead: false,
    authUsersDataRead: false,
    businessRecordsChanged: false,
    businessHeadersChanged: false,
    reportTab: KS_P3.AUDIT_TAB
  }));
  return {success: allOk, results: rows, reportTab: KS_P3.AUDIT_TAB};
}

/* --------------------------- ID ALLOCATION --------------------------- */

function ksP3ReadColumnValues_(sh, col) {
  const lastRow = sh.getLastRow();
  if (lastRow < 2) return [];
  return sh.getRange(2, col, lastRow - 1, 1).getDisplayValues()
    .map(r => String(r[0] || '').trim()).filter(Boolean);
}

function ksP3AllocateIdLocked_(ss, tableName) {
  const cfg = KS_P3.TABLES[tableName];
  if (!cfg || !cfg.prefix) {
    throw new Error('Automatic ID allocation is not approved for ' + tableName + '. Use an owner-approved ID.');
  }

  const target = ksP3GetSheet_(ss, tableName);
  const targetMap = ksP3RequireHeaders_(target, [cfg.idHeader]);
  const ledger = ksP3GetSheet_(ss, KS_P3.ALLOCATION_TAB);
  const ledgerMap = ksP3RequireHeaders_(ledger, KS_P3.ALLOCATION_HEADERS);

  const used = new Set(ksP3ReadColumnValues_(target, targetMap[cfg.idHeader]).map(v => v.toUpperCase()));
  const ledgerTabValues = ksP3ReadColumnValues_(ledger, ledgerMap.tab_name);
  const ledgerIdValues = ksP3ReadColumnValues_(ledger, ledgerMap.allocated_id);
  // Read the ledger's two relevant columns only, aligned by row.
  const ledgerLast = ledger.getLastRow();
  if (ledgerLast >= 2) {
    const tabVals = ledger.getRange(2, ledgerMap.tab_name, ledgerLast - 1, 1).getDisplayValues();
    const idVals = ledger.getRange(2, ledgerMap.allocated_id, ledgerLast - 1, 1).getDisplayValues();
    for (let i = 0; i < tabVals.length; i++) {
      if (String(tabVals[i][0]).trim() === tableName && String(idVals[i][0]).trim()) {
        used.add(String(idVals[i][0]).trim().toUpperCase());
      }
    }
  }

  let max = 0;
  let width = 4;
  const pattern = new RegExp('^' + cfg.prefix + '-(\\d+)$', 'i');
  used.forEach(id => {
    const m = id.match(pattern);
    if (m) {
      max = Math.max(max, Number(m[1]));
      width = Math.max(width, m[1].length);
    }
  });

  let candidate;
  do {
    max++;
    candidate = cfg.prefix + '-' + String(max).padStart(width, '0');
  } while (used.has(candidate.toUpperCase()));

  const nonce = Utilities.getUuid();
  const allocationId = 'ALC-' + Utilities.getUuid().replace(/-/g, '').substring(0, 12).toUpperCase();
  const row = new Array(ledger.getLastColumn()).fill('');
  row[ledgerMap.allocation_id - 1] = allocationId;
  row[ledgerMap.tab_name - 1] = tableName;
  row[ledgerMap.allocated_id - 1] = candidate;
  row[ledgerMap.nonce - 1] = nonce;
  row[ledgerMap.created_at - 1] = ksP3Now_();
  ledger.appendRow(row);
  SpreadsheetApp.flush();

  // Verify the exact claim row. Lock protects this script project, not other projects.
  const newRow = ledger.getLastRow();
  const verify = ledger.getRange(newRow, 1, 1, ledger.getLastColumn()).getValues()[0];
  if (String(verify[ledgerMap.nonce - 1]) !== nonce ||
      String(verify[ledgerMap.allocated_id - 1]) !== candidate ||
      String(verify[ledgerMap.tab_name - 1]) !== tableName) {
    throw new Error('ID reservation verification failed. Do not reuse the candidate; inspect IdAllocations.');
  }
  return candidate;
}

function ksP3ReserveId_(tableName) {
  const ss = ksP3GetWorkbook_();
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const id = ksP3AllocateIdLocked_(ss, tableName);
    ksP3AuditLog_(ss, 'RESERVE_ID', tableName, id, 'SUCCESS', 'ID reserved; no master record created.');
    SpreadsheetApp.flush();
    SpreadsheetApp.getUi().alert('ID reserved: ' + id + '\nNo master record was created.');
    console.log('KS_P3_ID_RESERVED ' + JSON.stringify({table: tableName, id: id, success: true}));
    return id;
  } finally {
    lock.releaseLock();
  }
}
function KS_P3_RESERVE_PRODUCT_ID() { return ksP3ReserveId_('Products'); }
function KS_P3_RESERVE_CUSTOMER_ID() { return ksP3ReserveId_('Customers'); }
function KS_P3_RESERVE_SUPPLIER_ID() { return ksP3ReserveId_('Suppliers'); }

/* --------------------------- RECORD WRITING --------------------------- */

function ksP3CheckUnique_(sh, headerMap, header, value) {
  const col = headerMap[header];
  if (!col) throw new Error('Unique-check header missing: ' + header);
  const existing = ksP3ReadColumnValues_(sh, col).map(v => v.toLowerCase());
  if (existing.indexOf(String(value).trim().toLowerCase()) >= 0) {
    throw new Error('Duplicate ' + header + ': ' + value + '. No record created.');
  }
}

function ksP3AppendByHeaders_(sh, headerMap, record) {
  const row = new Array(sh.getLastColumn()).fill('');
  Object.keys(record).forEach(key => {
    if (!headerMap[key]) throw new Error('Cannot write unknown live field: ' + key);
    row[headerMap[key] - 1] = record[key];
  });
  sh.appendRow(row);
  SpreadsheetApp.flush();
  return sh.getLastRow();
}

function ksP3CreateWithAllocatedId_(tableName, buildRecord) {
  const ss = ksP3GetWorkbook_();
  const ui = SpreadsheetApp.getUi();
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sh = ksP3GetSheet_(ss, tableName);
    const cfg = KS_P3.TABLES[tableName];
    const map = ksP3RequireHeaders_(sh, cfg.required);
    const id = ksP3AllocateIdLocked_(ss, tableName);
    const record = buildRecord(ui, id);
    if (!record) return null;

    cfg.unique.forEach(h => {
      if (record[h] !== undefined && record[h] !== '') ksP3CheckUnique_(sh, map, h, record[h]);
    });
    record[cfg.idHeader] = id;
    const rowNumber = ksP3AppendByHeaders_(sh, map, record);
    ksP3AuditLog_(ss, 'CREATE_MASTER_RECORD', tableName, id, 'SUCCESS',
                  'New record appended at row ' + rowNumber + '. No existing record changed.');
    SpreadsheetApp.flush();
    ui.alert(tableName + ' created successfully.\nID: ' + id + '\nRow: ' + rowNumber);
    console.log('KS_P3_MASTER_RECORD_CREATED ' + JSON.stringify({
      table: tableName, id: id, row: rowNumber, success: true
    }));
    return id;
  } catch (err) {
    // If an ID was reserved before the user cancelled or validation failed,
    // that ID remains in IdAllocations as a harmless reserved/unused claim.
    console.error('KS_P3_CREATE_FAILED ' + JSON.stringify({
      table: tableName, message: String(err.message || err)
    }));
    throw err;
  } finally {
    lock.releaseLock();
  }
}

function KS_P3_ADD_PRODUCT() {
  return ksP3CreateWithAllocatedId_('Products', function(ui, id) {
    const sku = ksP3Prompt_(ui, 'Add Product', 'Product SKU (must be unique):', true);
    const productName = ksP3Prompt_(ui, 'Add Product', 'Product name:', true);
    const category = ksP3Prompt_(ui, 'Add Product', 'Category:', true);
    const variant = ksP3Prompt_(ui, 'Add Product', 'Variant:', true);
    const weight = ksP3Number_(ksP3Prompt_(ui, 'Add Product', 'Pack weight in grams:', true), 'Pack weight', true);
    const unit = ksP3Prompt_(ui, 'Add Product', 'Selling unit (for example, pack):', true);
    const retailOnly = ksP3PromptYesNo_(ui, 'Add Product', 'Retail pack only?', false);
    const active = ksP3PromptYesNo_(ui, 'Add Product', 'Set product active?', true);
    const notes = ksP3Prompt_(ui, 'Add Product', 'Notes (optional):', false);
    return {
      sku: sku, product_name: productName, category: category, variant: variant,
      pack_weight_g: weight, selling_unit: unit,
      retail_pack_only: retailOnly, active: active, notes: notes
    };
  });
}

function KS_P3_ADD_RAW_MATERIAL() {
  const ss = ksP3GetWorkbook_();
  const ui = SpreadsheetApp.getUi();
  const sh = ksP3GetSheet_(ss, 'RawMaterials');
  const map = ksP3RequireHeaders_(sh, KS_P3.TABLES.RawMaterials.required);
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const id = ksP3Prompt_(ui, 'Add Raw Material',
      'Enter an owner-approved Raw Material ID.\nAutomatic RWM allocation is disabled pending prefix-policy approval:', true);
    ksP3CheckUnique_(sh, map, 'raw_material_id', id);
    const name = ksP3Prompt_(ui, 'Add Raw Material', 'Material name:', true);
    const unit = ksP3Prompt_(ui, 'Add Raw Material', 'Unit (kg, g, litre, piece, etc.):', true);
    const category = ksP3Prompt_(ui, 'Add Raw Material', 'Category (optional):', false);
    const rateText = ksP3Prompt_(ui, 'Add Raw Material', 'Rate per unit (leave blank if not approved/known):', false);
    const rate = rateText ? ksP3Number_(rateText, 'Rate per unit', true) : '';
    const rateStatus = ksP3Prompt_(ui, 'Add Raw Material', 'Rate status (optional, exact business wording):', false);
    const minText = ksP3Prompt_(ui, 'Add Raw Material', 'Minimum stock (leave blank if not set):', false);
    const minStock = minText ? ksP3Number_(minText, 'Minimum stock', true) : '';
    const active = ksP3PromptYesNo_(ui, 'Add Raw Material', 'Set material active?', true);
    const notes = ksP3Prompt_(ui, 'Add Raw Material', 'Notes (optional):', false);

    const record = {
      raw_material_id: id, material_name: name, unit: unit,
      // No opening/current stock initialization here. Stock must enter through
      // the approved opening-stock or stock-ledger workflow.
      opening_stock: '', current_stock: '', minimum_stock: minStock,
      active: active, notes: notes, rate_per_unit: rate,
      rate_status: rateStatus, category: category,
      created_at: ksP3Now_(), created_by: ksP3Actor_()
    };
    const rowNumber = ksP3AppendByHeaders_(sh, map, record);
    ksP3AuditLog_(ss, 'CREATE_MASTER_RECORD', 'RawMaterials', id, 'SUCCESS',
                  'New raw material appended at row ' + rowNumber + '; stock balances left blank.');
    ui.alert('Raw Material created.\nID: ' + id + '\nRow: ' + rowNumber +
             '\nOpening/current stock were left blank.');
    console.log('KS_P3_MASTER_RECORD_CREATED ' + JSON.stringify({
      table: 'RawMaterials', id: id, row: rowNumber, success: true,
      stockInitialized: false
    }));
    return id;
  } finally {
    lock.releaseLock();
  }
}

function KS_P3_ADD_CUSTOMER() {
  return ksP3CreateWithAllocatedId_('Customers', function(ui, id) {
    const type = ksP3Prompt_(ui, 'Add Customer', 'Customer type (use your approved category wording):', true);
    const shop = ksP3Prompt_(ui, 'Add Customer', 'Shop/business name:', false);
    const person = ksP3Prompt_(ui, 'Add Customer', 'Customer / shopkeeper name:', true);
    const mobile = ksP3Prompt_(ui, 'Add Customer', 'Mobile number (not treated as unique):', true);
    const alt = ksP3Prompt_(ui, 'Add Customer', 'Alternate mobile (optional):', false);
    const address = ksP3Prompt_(ui, 'Add Customer', 'Address:', false);
    const locality = ksP3Prompt_(ui, 'Add Customer', 'Locality / area:', false);
    const city = ksP3Prompt_(ui, 'Add Customer', 'City:', false);
    const mapLocation = ksP3Prompt_(ui, 'Add Customer', 'Map location / map link (optional):', false);
    const gstin = ksP3Prompt_(ui, 'Add Customer', 'GSTIN (optional):', false);
    const active = ksP3PromptYesNo_(ui, 'Add Customer', 'Set customer active?', true);
    const notes = ksP3Prompt_(ui, 'Add Customer', 'Notes (optional):', false);
    return {
      customer_type: type, shop_name: shop, shopkeeper_name: person,
      mobile: mobile, alternate_mobile: alt, address: address,
      locality_area: locality, city: city, map_location: mapLocation,
      active: active, created_at: ksP3Now_(), notes: notes, gstin: gstin
    };
  });
}

function KS_P3_ADD_SUPPLIER() {
  return ksP3CreateWithAllocatedId_('Suppliers', function(ui, id) {
    const name = ksP3Prompt_(ui, 'Add Supplier', 'Supplier name:', true);
    const contact = ksP3Prompt_(ui, 'Add Supplier', 'Contact person (optional):', false);
    const mobile = ksP3Prompt_(ui, 'Add Supplier', 'Mobile (optional):', false);
    const email = ksP3Prompt_(ui, 'Add Supplier', 'Email (optional):', false);
    const address = ksP3Prompt_(ui, 'Add Supplier', 'Address (optional):', false);
    const city = ksP3Prompt_(ui, 'Add Supplier', 'City (optional):', false);
    const gstin = ksP3Prompt_(ui, 'Add Supplier', 'GSTIN (optional):', false);
    const termsText = ksP3Prompt_(ui, 'Add Supplier', 'Payment terms in days (leave blank if not agreed):', false);
    const terms = termsText ? ksP3Number_(termsText, 'Payment terms days', true) : '';
    const openingText = ksP3Prompt_(ui, 'Add Supplier', 'Opening balance (leave blank unless verified):', false);
    const opening = openingText ? Number(openingText) : '';
    if (openingText && !Number.isFinite(opening)) throw new Error('Opening balance must be numeric.');
    const active = ksP3PromptYesNo_(ui, 'Add Supplier', 'Set supplier active?', true);
    const notes = ksP3Prompt_(ui, 'Add Supplier', 'Notes (optional):', false);
    return {
      supplier_name: name, contact_person: contact, mobile: mobile,
      email: email, address: address, city: city, gstin: gstin,
      payment_terms_days: terms, opening_balance: opening,
      active: active, notes: notes, created_at: ksP3Now_(), created_by: ksP3Actor_()
    };
  });
}

/* --------------------------- USERS SAFE PROFILE --------------------------- */

function KS_P3_UPDATE_USER_PROFILE() {
  const ss = ksP3GetWorkbook_();
  const ui = SpreadsheetApp.getUi();
  const sh = ksP3GetSheet_(ss, 'Users');
  const map = ksP3RequireHeaders_(sh, ['user_id'].concat(Object.keys(KS_P3.USER_SAFE_FIELDS)));
  const userId = ksP3Prompt_(ui, 'Safe User Profile Update', 'Enter the exact user_id:', true);

  // Read only user_id column to locate the row. Do not read complete employee rows.
  const lastUserRow = sh.getLastRow();
  const idCells = lastUserRow >= 2
    ? sh.getRange(2, map.user_id, lastUserRow - 1, 1).getDisplayValues()
    : [];
  const matches = [];
  idCells.forEach((r, i) => {
    const v = String(r[0] || '').trim();
    if (v.toLowerCase() === userId.toLowerCase()) matches.push(i + 2);
  });
  if (matches.length !== 1) {
    throw new Error(matches.length === 0
      ? 'User ID not found. No changes made.'
      : 'Duplicate user_id found. No changes made; resolve through an approved data repair process.');
  }

  const fieldChoices = Object.keys(KS_P3.USER_SAFE_FIELDS);
  const choiceText = fieldChoices.map((f, i) => (i + 1) + '. ' + KS_P3.USER_SAFE_FIELDS[f] + ' (' + f + ')').join('\n');
  const choice = ksP3Prompt_(ui, 'Safe User Profile Update',
    'Choose one field by number:\n' + choiceText, true);
  const n = Number(choice);
  if (!Number.isInteger(n) || n < 1 || n > fieldChoices.length) throw new Error('Invalid field selection. No changes made.');
  const field = fieldChoices[n - 1];
  const newValue = ksP3Prompt_(ui, 'Safe User Profile Update',
    'Enter new value for ' + KS_P3.USER_SAFE_FIELDS[field] + ':', true);

  // Only the selected cell is written. No full-row read or rewrite.
  const row = matches[0];
  const oldValue = sh.getRange(row, map[field]).getDisplayValue();
  sh.getRange(row, map[field]).setValue(newValue);
  if (map.updated_at) sh.getRange(row, map.updated_at).setValue(ksP3Now_());
  ksP3AuditLog_(ss, 'UPDATE_SAFE_USER_PROFILE', 'Users', userId, 'SUCCESS',
                'Updated field ' + field + '. Old/new values intentionally omitted from audit log.');
  SpreadsheetApp.flush();
  ui.alert('User profile updated.\nUser ID: ' + userId + '\nField: ' + field);
  console.log('KS_P3_USER_PROFILE_UPDATED ' + JSON.stringify({
    userId: userId, field: field, success: true,
    authUsersAccessed: false, sensitiveFieldsRead: false
  }));
}
