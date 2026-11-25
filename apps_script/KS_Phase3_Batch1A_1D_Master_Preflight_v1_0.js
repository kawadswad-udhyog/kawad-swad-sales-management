/**
 * KAWAD SWAD ERP - PHASE 3 MASTER DATA BATCH 1A-1D
 * Version: 1.0.0
 *
 * PURPOSE
 * Performs a controlled readiness audit of:
 * 1A ID allocation + Settings
 * 1B Products + RawMaterials
 * 1C Customers + Suppliers
 * 1D Users + AuthUsers
 *
 * SAFE SCOPE:
 * - Reads only row-1 headers and first-column non-empty row counts for the
 *   eight named tabs. It does not read cell contents from AuthUsers.
 * - Reads ID policy and Phase 2 master-data rule registers.
 * - Writes only KS_P3_BATCH1_MASTER_AUDIT and appends KS_P3_MIGRATION_LOG.
 * - Does not create business records, modify business headers, validations,
 *   formulas, IDs, credentials, stock, prices, or configuration values.
 *
 * WHY THIS IS A GATE, NOT A DATA MIGRATION:
 * Phase 1 ID policy requires a shared server-side allocator used by API/UI
 * writers. A spreadsheet-only allocator cannot be authoritative for backend
 * writes. Backend implementation is required before production ID allocation.
 */

const KS_B1_CFG = Object.freeze({
  SPREADSHEET_ID: '1dI0_YOmGBxHtqa1mRpOdM_S_2le5-IDYpOapSeCWH7g',
  NAME_PREFIX: 'Kawad_Swad_Sales_Management_Google_Sheets',
  AUDIT_TAB: 'KS_P3_BATCH1_MASTER_AUDIT',
  LOG_TAB: 'KS_P3_MIGRATION_LOG',
  ID_POLICY_TAB: 'KS_P1_ID_POLICY',
  MASTER_RULES_TAB: 'KS_P2_MASTER_DATA_RULES',
  TABLES: [
    {name:'Settings', batch:'1A', required:['setting_key','setting_value','description'], unique:['setting_key'], mode:'PRESERVE_TEXT_VALUES'},
    {name:'IdAllocations', batch:'1A', required:['allocation_id','tab_name','allocated_id','nonce','created_at'], unique:['allocation_id','allocated_id','nonce'], mode:'BACKEND_SHARED_ALLOCATOR_REQUIRED'},
    {name:'Products', batch:'1B', required:['product_id','sku','product_name'], unique:['product_id','sku'], mode:'PRESERVE_MASTER'},
    {name:'RawMaterials', batch:'1B', required:['raw_material_id','material_name','unit'], unique:['raw_material_id'], mode:'PRESERVE_STOCK_AND_RATE'},
    {name:'Customers', batch:'1C', required:['customer_id','customer_type'], unique:['customer_id'], mode:'NO_MOBILE_UNIQUENESS_ASSUMPTION'},
    {name:'Suppliers', batch:'1C', required:['supplier_id','supplier_name'], unique:['supplier_id'], mode:'PRESERVE_PAYMENT_TERMS'},
    {name:'Users', batch:'1D', required:['user_id','full_name','role'], unique:['user_id'], mode:'RESTRICTED_NO_GENERIC_WRITES'},
    {name:'AuthUsers', batch:'1D', required:['auth_id','user_id','username','password_hash'], unique:['auth_id','username'], mode:'HIGHLY_RESTRICTED_NO_READ_OR_WRITE'}
  ],
  AUDIT_HEADERS: ['batch','tab_name','tab_exists','header_count','missing_required_headers','duplicate_headers','nonempty_data_rows','unique_fields_to_check','policy_mode','result','notes'],
  LOG_HEADERS: ['timestamp','version','event','spreadsheet_id','spreadsheet_name','backup_url','live_tab_count','inventory_rows','business_schema_changed','details']
});

function KS_PHASE3_BATCH1_MASTER_PREFLIGHT() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    if (!ss || ss.getId() !== KS_B1_CFG.SPREADSHEET_ID ||
        !ss.getName().startsWith(KS_B1_CFG.NAME_PREFIX)) {
      throw new Error('STOP: This is not the approved Kawad Swad workbook.');
    }

    const policy = ksB1ReadRegister_(ss, KS_B1_CFG.ID_POLICY_TAB);
    const rules = ksB1ReadRegister_(ss, KS_B1_CFG.MASTER_RULES_TAB);
    if (policy.length < 2 || rules.length < 2) {
      throw new Error('STOP: ID policy or Phase 2 master rules register is missing.');
    }

    const policyText = policy.slice(1).map(r => String(r[2] || '')).join('\n');
    const requiredPolicyMarkers = [
      'shared server-side allocator',
      'idempotency key',
      'server-side locking',
      'Persist each committed business transaction to Google Sheets'
    ];
    const policyMissing = requiredPolicyMarkers.filter(x =>
      policyText.toLowerCase().indexOf(x.toLowerCase()) < 0);
    if (policyMissing.length) {
      throw new Error('STOP: ID policy verification failed: ' + policyMissing.join('; '));
    }

    const output = [KS_B1_CFG.AUDIT_HEADERS];
    const issues = [];
    KS_B1_CFG.TABLES.forEach(t => {
      const sh = ss.getSheetByName(t.name);
      if (!sh) {
        output.push([t.batch,t.name,'NO',0,t.required.join('; '),'',0,t.unique.join('; '),t.mode,'BLOCKED','Required tab missing']);
        issues.push(t.name + ': missing tab');
        return;
      }

      // AuthUsers: inspect only row-1 headers and dimensions; never read data cells.
      const lastCol = sh.getLastColumn();
      const headers = lastCol ? sh.getRange(1,1,1,lastCol).getDisplayValues()[0].map(x => String(x).trim()) : [];
      const missing = t.required.filter(h => headers.indexOf(h) < 0);
      const dupes = headers.filter((h,i) => h && headers.indexOf(h) !== i);
      let dataRows = 'NOT_SCANNED';
      if (t.name !== 'AuthUsers') {
        const lastRow = sh.getLastRow();
        if (lastRow > 1) {
          const ids = sh.getRange(2,1,lastRow-1,1).getDisplayValues();
          dataRows = ids.filter(r => String(r[0]).trim() !== '').length;
        } else dataRows = 0;
      }

      const result = missing.length || dupes.length ? 'BLOCKED' : 'STRUCTURE_OK_REVIEW_REQUIRED';
      if (result === 'BLOCKED') issues.push(t.name + ': header issue');
      output.push([t.batch,t.name,'YES',headers.length,missing.join('; '),[...new Set(dupes)].join('; '),dataRows,t.unique.join('; '),t.mode,result,
        t.name === 'AuthUsers' ? 'Sensitive rows were not read.' :
        'Header and first-column row count only; values and uniqueness not validated.']);
    });

    const audit = ksB1GetOutput_(ss, KS_B1_CFG.AUDIT_TAB, KS_B1_CFG.AUDIT_HEADERS);
    audit.clearContents();
    audit.getRange(1,1,output.length,output[0].length).setValues(output);
    audit.setFrozenRows(1);

    const log = ss.getSheetByName(KS_B1_CFG.LOG_TAB);
    if (!log) throw new Error('STOP: KS_P3_MIGRATION_LOG missing; audit report written, no business schema changed.');
    const logHeaders = log.getRange(1,1,1,10).getDisplayValues()[0];
    if (logHeaders.join('|') !== KS_B1_CFG.LOG_HEADERS.join('|')) {
      throw new Error('STOP: migration log headers do not match the approved 10-column contract.');
    }
    log.appendRow([new Date(),'1.0.0','BATCH1_MASTER_PREFLIGHT',ss.getId(),ss.getName(),'',
      ss.getSheets().length,output.length-1,false,
      'Readiness audit only. No business tabs, records, headers, formulas, validations, IDs or credentials changed.']);

    const result = {
      success: issues.length === 0,
      status: issues.length ? 'BLOCKED_FOR_REVIEW' : 'PREFLIGHT_COMPLETE_REVIEW_REQUIRED',
      workbookId: ss.getId(),
      batches: ['1A','1B','1C','1D'],
      auditedTabs: KS_B1_CFG.TABLES.length,
      authUsersDataRead: false,
      businessSchemaChanged: false,
      issues: issues,
      reportTab: KS_B1_CFG.AUDIT_TAB,
      nextGate: 'Review audit results, then implement the shared server-side allocator and approved backend contracts.'
    };
    console.log('KS_PHASE3_BATCH1_MASTER_PREFLIGHT_RESULT ' + JSON.stringify(result));
    return result;
  } finally {
    lock.releaseLock();
  }
}

function ksB1ReadRegister_(ss, name) {
  const sh = ss.getSheetByName(name);
  if (!sh) throw new Error('Required register missing: ' + name);
  const r = sh.getLastRow(), c = sh.getLastColumn();
  return r && c ? sh.getRange(1,1,r,c).getValues() : [];
}
function ksB1GetOutput_(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() > 0) {
    const existing = sh.getRange(1,1,1,headers.length).getDisplayValues()[0];
    if (existing.some(Boolean) && existing.join('|') !== headers.join('|')) {
      throw new Error('STOP: output tab has unexpected headers: ' + name);
    }
  }
  return sh;
}
